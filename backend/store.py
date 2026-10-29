"""Transactional public workflow. SQLite locally; PostgreSQL via DATABASE_URL.

No dependency on the author's motion_library database or original video paths.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import sqlite3
import time
import uuid
import zlib
from contextlib import contextmanager
from pathlib import Path

import numpy as np


SCHEMA = """
CREATE TABLE IF NOT EXISTS pwa_users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS pwa_submissions (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES pwa_users(id), label TEXT NOT NULL,
 language TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL,
 rights INTEGER NOT NULL, training INTEGER NOT NULL, research INTEGER NOT NULL DEFAULT 0, idempotency_key TEXT NOT NULL,
 moderation_status TEXT NOT NULL DEFAULT 'pending', processing_status TEXT NOT NULL DEFAULT 'not_started',
 source_status TEXT NOT NULL DEFAULT 'uploading', source_ref TEXT, source_metadata TEXT NOT NULL DEFAULT '{}',
 reason TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL,
 UNIQUE(owner_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS pwa_jobs (
 id TEXT PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE REFERENCES pwa_submissions(id),
 state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, lease_until DOUBLE PRECISION,
 lease_token TEXT, worker TEXT, error_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pwa_artifacts (
 submission_id TEXT PRIMARY KEY REFERENCES pwa_submissions(id), payload BLOB NOT NULL,
 checksum TEXT NOT NULL, metadata TEXT NOT NULL, backed_up INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pwa_audit (
 id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS pwa_training_runs (
 id TEXT PRIMARY KEY, state TEXT NOT NULL, snapshot TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}',
 reason TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL,
 lease_until DOUBLE PRECISION, lease_token TEXT
);
CREATE TABLE IF NOT EXISTS pwa_uploads (
 submission_id TEXT PRIMARY KEY REFERENCES pwa_submissions(id), received INTEGER NOT NULL DEFAULT 0,
 session_uri TEXT, file_id TEXT
);
"""


class DomainError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Connection:
    def __init__(self, raw, postgres): self.raw, self.postgres = raw, postgres
    def execute(self, sql, values=()):
        return self.raw.execute(sql.replace('?', '%s') if self.postgres else sql, values)


class Store:
    def __init__(self, location):
        self.location = str(location)
        self.postgres = self.location.startswith(('postgres://', 'postgresql://'))
        if not self.postgres: Path(location).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            for statement in SCHEMA.split(';'):
                if statement.strip(): db.execute(statement.replace(' BLOB ', ' BYTEA ') if self.postgres else statement)
            if self.postgres:
                db.execute('ALTER TABLE pwa_submissions ADD COLUMN IF NOT EXISTS research INTEGER NOT NULL DEFAULT 0')
                db.execute('ALTER TABLE pwa_training_runs ADD COLUMN IF NOT EXISTS lease_until DOUBLE PRECISION')
                db.execute('ALTER TABLE pwa_training_runs ADD COLUMN IF NOT EXISTS lease_token TEXT')
            else:
                columns={r['name'] for r in db.execute('PRAGMA table_info(pwa_submissions)').fetchall()}
                if 'research' not in columns:db.execute('ALTER TABLE pwa_submissions ADD COLUMN research INTEGER NOT NULL DEFAULT 0')
                columns={r['name'] for r in db.execute('PRAGMA table_info(pwa_training_runs)').fetchall()}
                for name,kind in [('lease_until','DOUBLE PRECISION'),('lease_token','TEXT')]:
                    if name not in columns:db.execute(f'ALTER TABLE pwa_training_runs ADD COLUMN {name} {kind}')
            if self.postgres:
                for table in ('pwa_users','pwa_submissions','pwa_jobs','pwa_artifacts','pwa_audit','pwa_training_runs','pwa_uploads'):
                    db.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                    # Supabase browser roles must never read artifacts, jobs or Drive session URIs.
                    for role in ('anon','authenticated'):
                        exists=db.execute('SELECT 1 FROM pg_roles WHERE rolname=?',(role,)).fetchone()
                        if exists:db.execute(f'REVOKE ALL ON {table} FROM {role}')

    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            raw = psycopg.connect(self.location, row_factory=dict_row)
        else:
            raw = sqlite3.connect(self.location, timeout=30)
            raw.row_factory = sqlite3.Row
            raw.execute('PRAGMA foreign_keys=ON')
            raw.execute('BEGIN IMMEDIATE')
        try:
            db = Connection(raw, self.postgres)
            # A small pilot serializes workflow writes; replace with per-row locking at scale.
            if self.postgres: db.execute('SELECT pg_advisory_xact_lock(730281)')
            yield db
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally: raw.close()

    def user(self, identity, email, name, *, moderator=False):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM pwa_users WHERE id=?', (identity,)).fetchone()
            if row is None:
                db.execute('INSERT INTO pwa_users(id,email,name,role) VALUES(?,?,?,?)',
                           (identity, email, name[:100], 'moderator' if moderator else 'user'))
            else:
                db.execute('UPDATE pwa_users SET email=?,name=?,role=? WHERE id=?',
                           (email, name[:100], 'moderator' if moderator else 'user', identity))
            return dict(db.execute('SELECT * FROM pwa_users WHERE id=?', (identity,)).fetchone())

    def user_by_id(self, identity):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM pwa_users WHERE id=?', (identity,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def require_mod(actor):
        if not actor or actor['role'] != 'moderator': raise DomainError('Требуются права модератора.', 403)

    def _row(self, db, identifier):
        row = db.execute('SELECT * FROM pwa_submissions WHERE id=?', (identifier,)).fetchone()
        if row is None: raise DomainError('Материал не найден.', 404)
        return dict(row)

    @staticmethod
    def _access(actor, row):
        if not actor or (actor['id'] != row['owner_id'] and actor['role'] != 'moderator'):
            raise DomainError('Материал недоступен.', 403)

    @staticmethod
    def public_row(row):
        return {k: v for k, v in dict(row).items() if k not in ('source_ref', 'source_metadata', 'idempotency_key')}

    def _audit(self, db, row_id, actor, action, detail=''):
        db.execute('INSERT INTO pwa_audit VALUES(?,?,?,?,?,?)',
                   (str(uuid.uuid4()), row_id, actor, action, detail, time.time()))

    def _queue(self, db, row_id):
        db.execute("INSERT INTO pwa_jobs(id,submission_id,state) VALUES(?,?,'queued') ON CONFLICT(submission_id) DO NOTHING",
                   (str(uuid.uuid4()), row_id))

    def create_submission(self, actor, *, label, language, filename, size, mime, rights, training, idempotency_key, research=False):
        if not actor: raise DomainError('Войдите в аккаунт.', 401)
        label = label.strip()
        if not label or len(label) > 160: raise DomainError('Укажите название до 160 символов.')
        if language not in ('kk-KZ', 'ru-RU'): raise DomainError('Выберите язык материала.')
        if not rights: raise DomainError('Необходимо подтвердить права на запись.')
        if not isinstance(size, int) or size <= 0 or size > 100 * 1024 * 1024:
            raise DomainError('Размер видео должен быть от 1 байта до 100 МБ.')
        if mime not in ('video/mp4', 'video/webm', 'video/quicktime'): raise DomainError('Нужен MP4, WebM или MOV.')
        if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 100:
            raise DomainError('Некорректный идентификатор отправки.')
        safe_name = Path(filename.replace('\\', '/')).name[:180] or 'video.mp4'
        requested=(label,language,safe_name,size,mime,int(rights),int(training),int(research))
        with self.transaction() as db:
            existing = db.execute('SELECT * FROM pwa_submissions WHERE owner_id=? AND idempotency_key=?',
                                  (actor['id'], idempotency_key)).fetchone()
            if existing:
                stored=(existing['label'],existing['language'],existing['filename'],existing['size'],existing['mime'],
                        existing['rights'],existing['training'],existing['research'])
                if stored!=requested:raise DomainError('Настройки этой загрузки уже сохранены. Начните новую отправку для изменения согласия.',409)
                return self.public_row(existing)
            count = db.execute('SELECT COUNT(*) AS n FROM pwa_submissions WHERE owner_id=? AND created_at>?',
                               (actor['id'], time.time()-86400)).fetchone()['n']
            if count >= 30: raise DomainError('Достигнут дневной лимит: 30 материалов.', 429)
            identifier = str(uuid.uuid4())
            db.execute('''INSERT INTO pwa_submissions(id,owner_id,label,language,filename,size,mime,rights,training,research,
                       idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (identifier, actor['id'], label, language, safe_name, size, mime, int(rights), int(training), int(research), idempotency_key, time.time()))
            db.execute('INSERT INTO pwa_uploads(submission_id) VALUES(?)', (identifier,))
            return self.public_row(self._row(db, identifier))

    def complete_upload(self, actor, identifier, source_ref, metadata):
        with self.transaction() as db:
            row = self._row(db, identifier); self._access(actor, row)
            if row['source_status'] != 'uploading': return self.public_row(row)
            # The uploader's current role is re-read, not supplied by the browser.
            owner = db.execute('SELECT role FROM pwa_users WHERE id=?', (row['owner_id'],)).fetchone()
            trusted = owner['role'] == 'moderator'
            db.execute('''UPDATE pwa_submissions SET source_status='available',source_ref=?,source_metadata=?,
                moderation_status=?,processing_status=?,revision=revision+1 WHERE id=?''',
                (source_ref, json.dumps(metadata), 'approved' if trusted else 'pending', 'queued' if trusted else 'not_started', identifier))
            if trusted: self._queue(db, identifier)
            self._audit(db, identifier, actor['id'], 'trusted_uploader' if trusted else 'submitted')
            return self.public_row(self._row(db, identifier))

    def submission(self, actor, identifier, *, private=False):
        with self.transaction() as db:
            row = self._row(db, identifier); self._access(actor, row)
            if private: return row
            result = self.public_row(row)
            result['history'] = [dict(r) for r in db.execute('SELECT action,detail,created_at FROM pwa_audit WHERE submission_id=? ORDER BY created_at', (identifier,)).fetchall()]
            art = db.execute('SELECT checksum,backed_up FROM pwa_artifacts WHERE submission_id=?', (identifier,)).fetchone()
            result['can_delete_source'] = bool(art and art['backed_up'] and row['processing_status']=='ready' and row['moderation_status']=='approved' and row['source_status']=='available')
            return result

    def submissions(self, actor, *, moderation=False):
        if moderation: self.require_mod(actor)
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM pwa_submissions ORDER BY created_at DESC' if moderation else
                              'SELECT * FROM pwa_submissions WHERE owner_id=? ORDER BY created_at DESC', () if moderation else (actor['id'],)).fetchall()
            return [self.public_row(r) for r in rows]

    def decide(self, actor, identifier, decision, reason, revision):
        self.require_mod(actor)
        if decision not in ('approved', 'rejected'): raise DomainError('Неизвестное решение.')
        if decision == 'rejected' and not reason.strip(): raise DomainError('Укажите причину отклонения.')
        with self.transaction() as db:
            row = self._row(db, identifier)
            if row['revision'] != revision or row['moderation_status'] != 'pending':
                raise DomainError('Материал уже изменился. Обновите очередь.', 409)
            if row['source_status'] != 'available': raise DomainError('Передача видео ещё не завершена.', 409)
            db.execute('UPDATE pwa_submissions SET moderation_status=?,reason=?,processing_status=?,revision=revision+1 WHERE id=?',
                       (decision, reason.strip()[:1000], 'queued' if decision=='approved' else 'not_started', identifier))
            if decision == 'approved': self._queue(db, identifier)
            self._audit(db, identifier, actor['id'], decision, reason.strip()[:1000])
            return self.public_row(self._row(db, identifier))

    def claim_job(self, worker, *, now=None, lease_seconds=180):
        now = time.time() if now is None else now
        with self.transaction() as db:
            exhausted=db.execute("SELECT submission_id FROM pwa_jobs WHERE state='running' AND attempt>=3 AND lease_until<?",(now,)).fetchall()
            for expired in exhausted:
                db.execute("UPDATE pwa_submissions SET processing_status='failed',reason=?,revision=revision+1 WHERE id=?",
                           ('Обработчик был остановлен несколько раз. Модератор может повторить задачу.',expired['submission_id']))
            db.execute("UPDATE pwa_jobs SET state='failed',error_code='worker_lease_exhausted' WHERE state='running' AND attempt>=3 AND lease_until<?",(now,))
            row = db.execute('''SELECT j.* FROM pwa_jobs j JOIN pwa_submissions s ON s.id=j.submission_id
                WHERE s.moderation_status='approved' AND j.attempt<3 AND
                (j.state='queued' OR (j.state='running' AND j.lease_until<?)) ORDER BY s.created_at LIMIT 1''', (now,)).fetchone()
            if row is None: return None
            token = str(uuid.uuid4())
            db.execute("UPDATE pwa_jobs SET state='running',attempt=attempt+1,lease_until=?,lease_token=?,worker=? WHERE id=?",
                       (now+lease_seconds, token, worker, row['id']))
            db.execute("UPDATE pwa_submissions SET processing_status='running' WHERE id=?", (row['submission_id'],))
            return dict(db.execute('SELECT * FROM pwa_jobs WHERE id=?', (row['id'],)).fetchone())

    def withdraw(self,actor,identifier,reason,revision):
        if not reason.strip():raise DomainError('Укажите причину отзыва.')
        with self.transaction() as db:
            row=self._row(db,identifier);self._access(actor,row)
            if row['revision']!=revision:raise DomainError('Материал изменился. Обновите страницу.',409)
            db.execute("UPDATE pwa_submissions SET moderation_status='rejected',training=0,research=0,reason=?,revision=revision+1 WHERE id=?",(reason.strip()[:1000],identifier))
            db.execute("UPDATE pwa_jobs SET state='cancelled',lease_token=NULL WHERE submission_id=? AND state IN ('queued','running')",(identifier,))
            if row['processing_status'] in ('queued','running'):
                db.execute("UPDATE pwa_submissions SET processing_status='not_started' WHERE id=?",(identifier,))
            # Conservative invalidation: none of these unpublished candidates may be promoted.
            db.execute("UPDATE pwa_training_runs SET state='invalidated',reason=? WHERE state IN ('queued','waiting','running','candidate')",
                       ('Материал отозван. Требуется новый снимок разрешённого набора.',))
            self._audit(db,identifier,actor['id'],'withdrawn',reason.strip()[:1000])
            return self.public_row(self._row(db,identifier))

    def heartbeat(self, job_id, token):
        with self.transaction() as db:
            result = db.execute("UPDATE pwa_jobs SET lease_until=? WHERE id=? AND lease_token=? AND state='running'",
                                (time.time()+180, job_id, token))
            return result.rowcount == 1

    @staticmethod
    def pack(sequence, metadata):
        array = np.asarray(sequence, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] != 162 or array.shape[0] > 3600 or not np.isfinite(array).all():
            raise ValueError('Некорректный массив координат: ожидается до 3600 кадров по 162 признака.')
        fps = float(metadata.get('fps', 30))
        if not math.isfinite(fps) or fps <= 0: raise ValueError('Некорректная частота кадров.')
        buffer = io.BytesIO(); np.save(buffer, array, allow_pickle=False)
        payload = zlib.compress(buffer.getvalue())
        meta = {**metadata, 'fps': fps, 'shape': list(array.shape), 'dtype': 'float32', 'schema_version': 1}
        return payload, hashlib.sha256(payload).hexdigest(), json.dumps(meta, ensure_ascii=False, allow_nan=False)

    @staticmethod
    def unpack(row):
        payload = bytes(row['payload'])
        if hashlib.sha256(payload).hexdigest() != row['checksum']: raise ValueError('Контрольная сумма не совпала.')
        array = np.load(io.BytesIO(zlib.decompress(payload)), allow_pickle=False)
        metadata = json.loads(row['metadata'])
        if list(array.shape) != metadata['shape'] or not np.isfinite(array).all(): raise ValueError('Массив повреждён.')
        return array, metadata

    def finish_job(self, job_id, token, sequence, metadata):
        payload, checksum, meta = self.pack(sequence, metadata)
        with self.transaction() as db:
            job = db.execute('SELECT * FROM pwa_jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['state'] != 'running' or job['lease_token'] != token:
                raise DomainError('Задание уже передано другому обработчику.', 409)
            identifier = job['submission_id']
            db.execute('''INSERT INTO pwa_artifacts(submission_id,payload,checksum,metadata) VALUES(?,?,?,?)
                ON CONFLICT(submission_id) DO UPDATE SET payload=excluded.payload,checksum=excluded.checksum,metadata=excluded.metadata,backed_up=0''',
                (identifier, payload, checksum, meta))
            self.unpack(db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?', (identifier,)).fetchone())
            usable = metadata.get('training_eligible', True) is True
            db.execute('UPDATE pwa_submissions SET processing_status=?,revision=revision+1 WHERE id=?', ('ready' if usable else 'needs_video', identifier))
            db.execute("UPDATE pwa_jobs SET state='done',lease_until=NULL WHERE id=?", (job_id,))
            self._audit(db, identifier, 'worker', 'coordinates_saved', checksum)

    def fail_job(self, job_id, token, reason):
        with self.transaction() as db:
            job = db.execute('SELECT * FROM pwa_jobs WHERE id=? AND lease_token=?', (job_id,token)).fetchone()
            if not job or job['state'] != 'running': return
            db.execute("UPDATE pwa_jobs SET state='failed',error_code=?,lease_until=NULL WHERE id=?", (reason[:500], job_id))
            db.execute("UPDATE pwa_submissions SET processing_status='failed',reason=?,revision=revision+1 WHERE id=?", (reason[:500],job['submission_id']))

    def retry(self, actor, identifier):
        self.require_mod(actor)
        with self.transaction() as db:
            row = self._row(db,identifier)
            if row['processing_status'] != 'failed' or row['source_status']!='available': raise DomainError('Повтор недоступен.',409)
            db.execute("UPDATE pwa_jobs SET state='queued',attempt=0,error_code='' WHERE submission_id=?", (identifier,))
            db.execute("UPDATE pwa_submissions SET processing_status='queued',reason='' WHERE id=?", (identifier,))

    def gestures(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('''SELECT s.id,s.label,s.language,a.metadata,a.checksum AS version FROM pwa_submissions s
                JOIN pwa_artifacts a ON a.submission_id=s.id WHERE s.moderation_status='approved'
                AND s.processing_status='ready' ORDER BY s.label''').fetchall()]

    def motion(self, identifier):
        with self.transaction() as db:
            row = self._row(db, identifier)
            if row['moderation_status']!='approved' or row['processing_status']!='ready': raise DomainError('Жест пока недоступен.',404)
            artifact = db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?',(identifier,)).fetchone()
            array, metadata = self.unpack(artifact)
            return {'id':identifier, 'label':row['label'], 'language':row['language'], 'sequence':array.tolist(), 'fps':metadata['fps'], 'metadata':metadata, 'version':artifact['checksum']}

    def mark_backed_up(self, identifier):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?',(identifier,)).fetchone()
            if not row: raise DomainError('Нет координат.',409)
            self.unpack(row)
            db.execute('UPDATE pwa_artifacts SET backed_up=1 WHERE submission_id=?',(identifier,))

    def request_source_deletion(self, actor, identifier):
        with self.transaction() as db:
            row=self._row(db,identifier); self._access(actor,row)
            if row['source_status']=='deleted': return row
            if row['source_status']=='not_imported': raise DomainError('Видео для этого материала не переносилось.',409)
            artifact=db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?',(identifier,)).fetchone()
            if not artifact or not artifact['backed_up'] or row['processing_status']!='ready' or row['moderation_status']!='approved':
                raise DomainError('Сначала нужны проверенные координаты и резервная копия.',409)
            self.unpack(artifact)
            db.execute("UPDATE pwa_submissions SET source_status='delete_requested' WHERE id=?",(identifier,))
            self._audit(db,identifier,actor['id'],'delete_source_requested')
            return row

    def finish_source_deletion(self, identifier):
        with self.transaction() as db:
            db.execute("UPDATE pwa_submissions SET source_status='deleted',source_ref=NULL,revision=revision+1 WHERE id=? AND source_status='delete_requested'",(identifier,))

    def training_data(self):
        with self.transaction() as db:
            rows=db.execute('''SELECT s.id,s.label,s.owner_id,a.* FROM pwa_submissions s JOIN pwa_artifacts a ON a.submission_id=s.id
                WHERE s.moderation_status='approved' AND s.processing_status='ready' AND s.training=1 ORDER BY s.id''').fetchall()
            return [(dict(r), *self.unpack(r)) for r in rows]

    def training_snapshot(self):
        rows=self.training_data(); labels={}; groups={}
        for row, array, meta in rows:
            labels[row['label']]=labels.get(row['label'],0)+1
            groups.setdefault(row['label'],set()).add(meta.get('signer_id') or row['owner_id'])
        eligible=len(labels)>=2 and all(len(g)>=2 for g in groups.values())
        return {'count':len(rows),'classes':labels,'groups':{k:len(v) for k,v in groups.items()},'eligible':eligible,
                'reason':'' if eligible else 'Нужны минимум два класса и два независимых исполнителя в каждом классе.',
                'fingerprint':hashlib.sha256('|'.join(r['id']+r['checksum'] for r,_,_ in rows).encode()).hexdigest()}
