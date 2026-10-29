"""Durable extraction worker. ML dependencies are loaded only for actual jobs."""
from pathlib import Path
import json
import logging
import tempfile
import threading
import time

import numpy as np

from backend.store import DomainError


def extract(path,row):
    from src.motion_db import import_video_motion,get_motion_clip
    with tempfile.TemporaryDirectory() as directory:
        db_path=Path(directory)/'extraction.sqlite3'
        identifier=import_video_motion(row['label'],path,phrase=row['label'],language=row['language'],
            source='dosym-pwa-upload',license_name='uploader-permission',rights_confirmed=True,
            signer_id=row['owner_id'],db_path=db_path)
        clip=get_motion_clip(identifier,db_path=db_path)
        if clip is None: raise ValueError('Не удалось перечитать извлечённые координаты.')
        return clip['sequence'],{**clip['metadata'],'fps':clip['fps'],'signer_id':row['owner_id'],
                                 'source':'dosym-pwa-upload','rights_confirmed':True}


def backup_artifact(store,settings,identifier):
    """Verified local copy for development; production needs operator backup confirmation."""
    if settings.environment!='development':return
    directory=settings.data_dir/'backups';directory.mkdir(parents=True,exist_ok=True)
    with store.transaction() as db:
        row=db.execute('SELECT * FROM pwa_artifacts WHERE submission_id=?',(identifier,)).fetchone()
        array,meta=store.unpack(row)
    target=directory/(identifier+'.npz')
    np.savez_compressed(target,sequence=array,metadata=np.array(json.dumps(meta,ensure_ascii=False)))
    with np.load(target,allow_pickle=False) as restored:
        if not np.array_equal(restored['sequence'],array):raise ValueError('Резервная копия не прошла проверку.')
    store.mark_backed_up(identifier)


def process_one(store,storage,settings,*,extractor=extract):
    job=store.claim_job('pwa-extractor')
    if not job:return False
    stopped=threading.Event()
    def heartbeat():
        while not stopped.wait(30):
            if not store.heartbeat(job['id'],job['lease_token']):break
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with store.transaction() as db: row=store._row(db,job['submission_id'])
        with storage.materialize(row) as path: sequence,metadata=extractor(path,row)
        store.finish_job(job['id'],job['lease_token'],sequence,metadata)
        # Backup errors do not invalidate successfully committed coordinates.
        try:backup_artifact(store,settings,row['id'])
        except (OSError,ValueError):logging.warning('Local backup was not verified; source deletion remains disabled.')
        from backend.training import schedule
        schedule(store,automatic=True)
    except Exception as error:
        # Never leak paths, tokens or external response bodies to public statuses.
        if isinstance(error,ModuleNotFoundError): message='Не установлены зависимости обработки. Проверьте окружение Python.'
        elif isinstance(error,DomainError): message=str(error)
        elif isinstance(error,ValueError): message='Не удалось получить пригодные координаты. Проверьте видимость рук и качество видео.'
        else: message='Обработка прервалась. Модератор может повторить задачу.'
        store.fail_job(job['id'],job['lease_token'],message)
        logging.warning('Extraction failed (%s); original retained.',type(error).__name__)
    finally: stopped.set();thread.join(timeout=1)
    return True


def loop(store,storage,settings,stop):
    while not stop.is_set():
        try:
            worked=process_one(store,storage,settings)
            from backend.training import process_training
            trained=process_training(store,settings)
            if not worked and not trained:stop.wait(2)
        except Exception:
            logging.exception('Worker loop interrupted; durable jobs remain in the database.')
            stop.wait(5)


if __name__=='__main__':
    from backend.settings import Settings,load_local_environment
    from backend.store import Store
    from backend.storage import DriveStorage,LocalStorage
    load_local_environment();settings=Settings()
    store=Store(settings.database_url or str(settings.data_dir/'public.sqlite3'))
    storage=DriveStorage(settings.data_dir) if settings.storage=='drive' else LocalStorage(settings.data_dir)
    stop=threading.Event()
    try:loop(store,storage,settings,stop)
    except KeyboardInterrupt:stop.set()
