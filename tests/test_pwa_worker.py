import tempfile
import unittest
from pathlib import Path
import numpy as np
from backend.store import Store
from backend.settings import Settings
from backend.worker import process_one
from backend.storage import LocalStorage
from backend.training import schedule

class WorkerTests(unittest.TestCase):
    def test_successful_processing_saves_backup_and_survives_real_file_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(data_dir=Path(folder));store=Store(str(Path(folder)/'public.sqlite3'));storage=LocalStorage(folder)
            mod=store.user('mod','mod@example.test','Mod',moderator=True)
            row=store.create_submission(mod,label='Сәлем',language='kk-KZ',filename='source.mp4',size=100,mime='video/mp4',rights=True,training=True,idempotency_key='worker-test-1')
            storage.path(row['id']).write_bytes(b'test-source')
            store.complete_upload(mod,row['id'],'local:'+row['id'],{})
            def extractor(path,row):return np.ones((10,162),dtype=np.float32),{'fps':30,'training_eligible':True}
            self.assertTrue(process_one(store,storage,settings,extractor=extractor))
            source=store.request_source_deletion(mod,row['id']);storage.delete(source);store.finish_source_deletion(row['id'])
            self.assertFalse(storage.path(row['id']).exists())
            reloaded=Store(str(Path(folder)/'public.sqlite3'))
            self.assertEqual(len(reloaded.motion(row['id'])['sequence']),10)
            self.assertEqual(reloaded.training_snapshot()['count'],1)
            self.assertEqual(schedule(reloaded)['state'],'waiting')

    def test_extraction_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(data_dir=Path(folder));store=Store(str(Path(folder)/'public.sqlite3'));storage=LocalStorage(folder)
            mod=store.user('mod','mod@example.test','Mod',moderator=True)
            row=store.create_submission(mod,label='Test',language='kk-KZ',filename='x.mp4',size=100,mime='video/mp4',rights=True,training=True,idempotency_key='worker-test-2')
            storage.path(row['id']).write_bytes(b'source');store.complete_upload(mod,row['id'],'local:'+row['id'],{})
            def extractor(*args):raise ValueError('Руки не видны в кадре.')
            process_one(store,storage,settings,extractor=extractor)
            self.assertEqual(store.submission(mod,row['id'])['processing_status'],'failed')
            self.assertTrue(storage.path(row['id']).exists())
            self.assertEqual(store.gestures(),[])
