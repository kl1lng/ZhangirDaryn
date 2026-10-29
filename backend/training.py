"""Batch model candidates. No implicit publication or overwrite of author weights."""
import importlib.util
import json
import time
import uuid
import threading
import os
import logging

from backend.store import DomainError


def runs(store):
    with store.transaction() as db:return [{k:v for k,v in dict(r).items() if k!='lease_token'} for r in db.execute('SELECT * FROM pwa_training_runs ORDER BY created_at DESC LIMIT 30').fetchall()]


def recover_interrupted(store,*,now=None):
    now=time.time() if now is None else now
    with store.transaction() as db:
        db.execute("UPDATE pwa_training_runs SET state='failed',reason=? WHERE state='running' AND (lease_until IS NULL OR lease_until<?)",
                   ('Предыдущий обработчик обучения остановился. Можно создать новый запуск; рабочие веса не изменены.',now))


def schedule(store,*,automatic=False):
    recover_interrupted(store)
    snapshot=store.training_snapshot()
    if not snapshot['eligible']:return {'state':'waiting','reason':snapshot['reason']}
    with store.transaction() as db:
        previous=db.execute('SELECT * FROM pwa_training_runs ORDER BY created_at DESC').fetchall()
        for row in previous:
            if row['state'] in ('queued','running'):return dict(row)
            if json.loads(row['snapshot'])['fingerprint']==snapshot['fingerprint'] and automatic:return dict(row)
        identifier=str(uuid.uuid4())
        db.execute("INSERT INTO pwa_training_runs(id,state,snapshot,created_at) VALUES(?,'queued',?,?)",
                   (identifier,json.dumps(snapshot),time.time()))
        return {'id':identifier,'state':'queued'}


def process_training(store,settings):
    recover_interrupted(store)
    tensorflow_available=importlib.util.find_spec('tensorflow') is not None
    with store.transaction() as db:
        run=db.execute("SELECT * FROM pwa_training_runs WHERE state IN ('queued','waiting') ORDER BY created_at LIMIT 1" if tensorflow_available else "SELECT * FROM pwa_training_runs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
        if run is None:return False
        identifier=run['id'];snapshot=json.loads(run['snapshot'])
        if not tensorflow_available:
            db.execute("UPDATE pwa_training_runs SET state='waiting',reason=? WHERE id=?",
                ('Для обучения требуется отдельное окружение с TensorFlow. На этом компьютере установлено только извлечение координат.',identifier))
            return True
        lease=str(uuid.uuid4())
        db.execute("UPDATE pwa_training_runs SET state='running',lease_until=?,lease_token=? WHERE id=?",(time.time()+180,lease,identifier))
    stopped=threading.Event()
    def heartbeat():
        while not stopped.wait(30):
            with store.transaction() as db:
                db.execute("UPDATE pwa_training_runs SET lease_until=? WHERE id=? AND lease_token=? AND state='running'",(time.time()+180,identifier,lease))
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        # A reproducible snapshot is rechecked before training; changes form a new candidate.
        if store.training_snapshot()['fingerprint']!=snapshot['fingerprint']:raise ValueError('Набор изменился. Создайте новый запуск.')
        os.environ.setdefault('TF_NUM_INTEROP_THREADS','2');os.environ.setdefault('TF_NUM_INTRAOP_THREADS','2')
        from src.training_data import prepare_training_data
        from src.train import train_model,save_model_and_labels
        sequences={};groups={}
        for row,array,meta in store.training_data():
            sequences.setdefault(row['label'],[]).append(array)
            groups.setdefault(row['label'],[]).append(meta.get('signer_id') or row['owner_id'])
        X,y,labels,group_array=prepare_training_data(sequences,groups_by_label=groups)
        directory=settings.data_dir/'models'/identifier;directory.mkdir(parents=True,exist_ok=True)
        model,history=train_model(X,y,num_classes=len(labels),epochs=settings.training_epochs,groups=group_array,checkpoint_dir=str(directory))
        save_model_and_labels(model,labels,model_path=str(directory/'candidate.h5'),map_path=str(directory/'labels.json'),training_metadata=snapshot)
        metrics={k:[float(x) for x in values] for k,values in history.history.items()}
        with store.transaction() as db:db.execute("UPDATE pwa_training_runs SET state='candidate',metrics=?,reason=?,lease_until=NULL WHERE id=? AND lease_token=? AND state='running'",
            (json.dumps(metrics),'Кандидат сохранён отдельно. Публикация требует независимой проверки качества.',identifier,lease))
    except Exception:
        logging.exception('Candidate training failed; active weights were not modified.')
        with store.transaction() as db:db.execute("UPDATE pwa_training_runs SET state='failed',reason=?,lease_until=NULL WHERE id=? AND lease_token=? AND state='running'",
            ('Обучение не завершено. Рабочие веса не изменены; проверьте окружение и независимость обучающих групп.',identifier,lease))
    finally:
        stopped.set();thread.join(timeout=1)
    return True


if __name__=='__main__':
    import argparse
    from backend.settings import Settings,load_local_environment
    from backend.store import Store
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    load_local_environment();settings=Settings();store=Store(settings.database_url or str(settings.data_dir/'public.sqlite3'))
    try:
        while True:
            worked=process_training(store,settings)
            if args.once:break
            if not worked:time.sleep(3)
    except KeyboardInterrupt:pass
