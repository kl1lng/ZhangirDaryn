import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from backend.store import Store
from backend.storage import DriveStorage
from backend.training import recover_interrupted

class RecoveryTests(unittest.TestCase):
    def test_interrupted_training_becomes_retryable_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(str(Path(folder)/'db.sqlite3'))
            with store.transaction() as db:
                db.execute("INSERT INTO pwa_training_runs(id,state,snapshot,created_at,lease_until) VALUES('run','running','{}',0,10)")
            recover_interrupted(store,now=11)
            with store.transaction() as db:
                self.assertEqual(db.execute("SELECT state FROM pwa_training_runs WHERE id='run'").fetchone()['state'],'failed')
    def test_drive_reconciles_lost_chunk_response(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'GOOGLE_DRIVE_FOLDER_ID':'test-folder'}):
            storage=DriveStorage(folder)
            with patch.object(storage,'headers',return_value={}),patch('httpx.put',return_value=httpx.Response(308,headers={'Range':'bytes=0-1023'})):
                state=storage.reconcile({'id':'test','size':2048},{'session_uri':'https://www.googleapis.com/test','received':0,'file_id':None})
            self.assertEqual(state['received'],1024)

    def test_expired_last_worker_attempt_becomes_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(str(Path(folder)/'db.sqlite3'));mod=store.user('mod','mod@example.test','Mod',moderator=True)
            row=store.create_submission(mod,label='Test',language='kk-KZ',filename='x.mp4',size=100,mime='video/mp4',rights=True,training=True,idempotency_key='recovery-test')
            store.complete_upload(mod,row['id'],'local:test',{})
            for now in (10,12,14): self.assertIsNotNone(store.claim_job('worker',now=now,lease_seconds=1))
            self.assertIsNone(store.claim_job('worker',now=16,lease_seconds=1))
            self.assertEqual(store.submission(mod,row['id'])['processing_status'],'failed')
