import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import numpy as np
from backend.store import Store
from backend.import_motion import import_clip
from backend.export_library import export_library


class PublicLibraryExportTests(unittest.TestCase):
    def test_only_approved_rights_cleared_coordinates_are_exported_without_private_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'public.sqlite3'
            store=Store(source)
            mod=store.user('owner','private@example.invalid','Private name',moderator=True)
            clip={'clip_id':1,'label':'Сәлем','language':'kk-KZ','sequence':np.ones((10,162),dtype=np.float32),
                  'metadata':{'fps':30,'training_eligible':True,'signer_id':'private-person','raw_video':'private.mp4'}}
            ready=import_clip(store,mod,clip,rights_confirmed=True)
            withdrawn=import_clip(store,mod,{**clip,'label':'Withdrawn'},rights_confirmed=True)
            store.withdraw(mod,withdrawn['id'],'withdrawn',withdrawn['revision'])
            no_rights=import_clip(store,mod,{**clip,'label':'No rights'},rights_confirmed=True)
            with closing(sqlite3.connect(source)) as db,db:
                db.execute('update pwa_submissions set rights=0 where id=?',(no_rights['id'],))
            before=source.read_bytes()
            report=export_library(source,root/'export')
            self.assertEqual(report['records'],1)
            catalog=json.loads((root/'export/catalog.json').read_text(encoding='utf-8'))
            self.assertEqual([r['id'] for r in catalog],[ready['id']])
            motion=json.loads((root/'export'/f"{ready['id']}.json").read_text(encoding='utf-8'))
            self.assertEqual(motion['sequence'],clip['sequence'].tolist())
            self.assertNotIn('body_pose_landmarks',catalog[0]['metadata'])
            camera=json.loads((root/'export/camera.json').read_text(encoding='utf-8'))
            self.assertEqual(len(camera['references']),1)
            self.assertEqual(np.shape(camera['references'][0]['sequence']),(16,126))
            text=json.dumps(motion)
            for private in ['private-person','private.mp4','private@example.invalid','Private name']:
                self.assertNotIn(private,text)
            self.assertEqual(source.read_bytes(),before)


if __name__=='__main__':unittest.main()
