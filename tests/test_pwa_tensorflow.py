"""Optional real training smoke test; synthetic coordinates, never real user data."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from backend.store import Store
from backend.settings import Settings
from backend.training import schedule,process_training,runs

@unittest.skipUnless(importlib.util.find_spec('tensorflow'),'Separate TensorFlow environment required')
class TensorFlowSmokeTest(unittest.TestCase):
    def test_real_candidate_training_uses_private_checkpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            settings=Settings(data_dir=Path(folder),training_epochs=1)
            store=Store(str(Path(folder)/'public.sqlite3'))
            rng=np.random.default_rng(42)
            for signer in range(4):
                user=store.user('signer-'+str(signer),f'signer-{signer}@example.test','Synthetic',moderator=True)
                for label in ('synthetic-a','synthetic-b'):
                    for sample in range(2):
                        row=store.create_submission(user,label=label,language='kk-KZ',filename='synthetic.mp4',size=100,
                            mime='video/mp4',rights=True,training=True,idempotency_key=label+'-'+str(sample))
                        store.complete_upload(user,row['id'],'synthetic:test-only',{})
                        job=store.claim_job('smoke')
                        array=rng.uniform(.1,.9,(30,162)).astype(np.float32)
                        store.finish_job(job['id'],job['lease_token'],array,{'fps':30,'signer_id':user['id'],'training_eligible':True})
            self.assertTrue(store.training_snapshot()['eligible'])
            run=schedule(store)
            author_models=Path(folder)/'author-models'
            with patch('config.MODELS_DIR',str(author_models)):
                self.assertTrue(process_training(store,settings))
            result=runs(store)[0]
            self.assertEqual(result['state'],'candidate',result['reason'])
            self.assertTrue((Path(folder)/'models'/run['id']/'candidate.h5').is_file())
            self.assertTrue((Path(folder)/'models'/run['id']/'labels.json').is_file())
            self.assertFalse(author_models.exists())
