"""Explicit, coordinate-only import from the author's SQLite motion library.

Dry run: python -m backend.import_motion --source data/motion_library.sqlite3 --clip-id 2
Apply requires --apply --confirm-rights. No videos or training consent are copied.
"""
import argparse
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time
import uuid
import zlib

import numpy as np

from backend.store import DomainError


PUBLIC_METADATA = frozenset({
    'coordinate_space', 'input_mirrored', 'image_aspect_ratio', 'frame_width', 'frame_height',
    'body_pose_status', 'body_pose_landmarks', 'body_pose_world_landmarks',
    'body_pose_coverage', 'left_arm_pose_coverage', 'right_arm_pose_coverage',
    'hand_detection_coverage', 'training_eligible', 'training_exclusion_reason',
})


def read_clip(source, clip_id):
    """Read one chosen clip without changing the source schema or database."""
    uri = Path(source).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('''SELECT c.id,g.lemma,g.phrase,g.language,c.fps,
            c.metadata_json,c.landmarks_zlib FROM motion_clips c
            JOIN gestures g ON g.id=c.gesture_id WHERE c.id=?''', (clip_id,)).fetchone()
    if row is None:
        raise DomainError('Клип не найден в исходной библиотеке.', 404)
    sequence = np.load(io.BytesIO(zlib.decompress(row['landmarks_zlib'])), allow_pickle=False)
    metadata = json.loads(row['metadata_json'] or '{}')
    if not isinstance(metadata, dict):
        raise ValueError('Некорректные метаданные клипа.')
    return {'clip_id': row['id'], 'label': row['phrase'] or row['lemma'],
            'language': row['language'], 'sequence': sequence,
            'metadata': {**metadata, 'fps': row['fps']}}


def eligible_clip_ids(source):
    """Select only clips explicitly cleared for rights and training quality."""
    uri = Path(source).resolve().as_uri() + '?mode=ro'
    selected = []
    totals = {'source_clips': 0, 'not_training_eligible': 0, 'rights_not_confirmed': 0,
              'both_exclusions': 0, 'selected': 0}
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute('SELECT id,metadata_json FROM motion_clips ORDER BY id').fetchall()
    for clip_id, raw_metadata in rows:
        totals['source_clips'] += 1
        metadata = json.loads(raw_metadata or '{}')
        if not isinstance(metadata, dict):
            raise ValueError(f'Некорректные метаданные клипа {clip_id}.')
        eligible = metadata.get('training_eligible') is True
        rights = metadata.get('rights_confirmed') is True
        if not eligible:
            totals['not_training_eligible'] += 1
        if not rights:
            totals['rights_not_confirmed'] += 1
        if not eligible and not rights:
            totals['both_exclusions'] += 1
        if eligible and rights:
            selected.append(clip_id)
    totals['selected'] = len(selected)
    return selected, totals


def import_clip(store, actor, clip, *, rights_confirmed=False):
    # Always re-read authority from the destination store.
    current = store.user_by_id(actor['id']) if actor else None
    store.require_mod(current)
    if not rights_confirmed:
        raise DomainError('Для публикации нужно подтвердить права на выбранный клип.')
    label = str(clip['label']).strip()
    if not label or len(label) > 160 or clip['language'] not in ('kk-KZ', 'ru-RU'):
        raise DomainError('Проверьте название и язык клипа.')
    if clip['metadata'].get('training_eligible') is False:
        raise DomainError('Исходный клип отмечен как непригодный. Сначала проверьте его качество.')
    metadata = {key: value for key, value in clip['metadata'].items() if key in PUBLIC_METADATA}
    metadata.update(fps=clip['metadata']['fps'], source='author-motion-import', source_clip_id=clip['clip_id'])
    payload, checksum, meta = store.pack(clip['sequence'], metadata)
    fingerprint = hashlib.sha256((label + '\n' + clip['language'] + '\n' + checksum + '\n' + meta).encode()).hexdigest()
    key = 'motion-import:' + fingerprint
    with store.transaction() as db:
        existing = db.execute('SELECT * FROM pwa_submissions WHERE idempotency_key=?', (key,)).fetchone()
        if existing:
            return store.public_row(existing)
        identifier = str(uuid.uuid4())
        db.execute('''INSERT INTO pwa_submissions(id,owner_id,label,language,filename,size,mime,
            rights,training,research,idempotency_key,moderation_status,processing_status,source_status,created_at)
            VALUES(?,?,?,?,?,?,?,1,0,0,?,'approved','ready','not_imported',?)''',
            (identifier, current['id'], label, clip['language'], 'motion-coordinates.npz',
             len(payload), 'application/x-numpy', key, time.time()))
        db.execute('INSERT INTO pwa_artifacts(submission_id,payload,checksum,metadata) VALUES(?,?,?,?)',
                   (identifier, payload, checksum, meta))
        store.unpack(db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?', (identifier,)).fetchone())
        store._audit(db, identifier, current['id'], 'coordinates_imported', checksum)
        return store.public_row(store._row(db, identifier))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--clip-id', type=int)
    selection.add_argument('--all-eligible', action='store_true',
                           help='Select only clips marked training_eligible and rights_confirmed.')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-rights', action='store_true')
    args = parser.parse_args()
    if args.all_eligible:
        clip_ids, selection_report = eligible_clip_ids(args.source)
        clips = [read_clip(args.source, clip_id) for clip_id in clip_ids]
    else:
        clips = [read_clip(args.source, args.clip_id)]
        selection_report = {'source_clips': 1, 'selected': 1}
    from backend.settings import Settings, load_local_environment
    from backend.store import Store
    load_local_environment()
    settings = Settings()
    if settings.environment != 'development' or settings.database_url:
        parser.error('Эта команда предназначена для локального импорта в SQLite.')
    # Validate even during a dry run.
    for clip in clips:
        Store.pack(clip['sequence'], clip['metadata'])
    shapes = {}
    for clip in clips:
        shape = '×'.join(str(value) for value in clip['sequence'].shape)
        shapes[shape] = shapes.get(shape, 0) + 1
    report = {'selection': selection_report,
              'unique_labels': len({(clip['label'], clip['language']) for clip in clips}),
              'array_shapes': shapes, 'applied': False, 'videos_imported': 0}
    if args.apply:
        if not args.confirm_rights:
            parser.error('--apply требует --confirm-rights для выбранной записи.')
        store = Store(settings.data_dir / 'public.sqlite3')
        with store.transaction() as db:
            row = db.execute("SELECT * FROM pwa_users WHERE lower(email)=? AND role='moderator'",
                             (settings.moderator_email,)).fetchone()
        if row is None:
            parser.error('Сначала войдите в PWA настроенным аккаунтом модератора.')
        from backend.worker import backup_artifact
        imported = []
        for clip in clips:
            result = import_clip(store, dict(row), clip, rights_confirmed=True)
            backup_artifact(store, settings, result['id'])
            imported.append(result['id'])
        report.update(applied=True, processed=len(imported))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
