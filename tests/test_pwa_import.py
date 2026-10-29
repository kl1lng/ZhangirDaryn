import json
import sqlite3
import tempfile
import unittest
import zlib
import io
from contextlib import closing
from pathlib import Path

import numpy as np

from backend.store import Store, DomainError
from backend.import_motion import read_clip, import_clip, eligible_clip_ids


class MotionImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'author.sqlite3'
        self.store = Store(self.root / 'public.sqlite3')
        self.mod = self.store.user('mod', 'mod@example.invalid', 'Moderator', moderator=True)
        self.user = self.store.user('user', 'user@example.invalid', 'User')
        self.array = np.ones((56, 162), dtype=np.float32)
        buffer = io.BytesIO()
        np.save(buffer, self.array, allow_pickle=False)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.executescript('''CREATE TABLE gestures(id INTEGER,lemma TEXT,phrase TEXT,language TEXT);
                CREATE TABLE motion_clips(id INTEGER,gesture_id INTEGER,fps REAL,metadata_json TEXT,landmarks_zlib BLOB);''')
            db.execute('INSERT INTO gestures VALUES(1,?,?,?)', ('сәлем', 'Сәлем', 'kk-KZ'))
            db.execute('INSERT INTO motion_clips VALUES(2,1,30,?,?)', (json.dumps({
                'training_eligible': True, 'rights_confirmed': True, 'body_pose_status': 'available',
                'body_pose_landmarks': [[[0.1, 0.2, 0.3, 1.0]] * 33] * 56,
                'raw_video': '/private/video.mp4', 'signer_id': 'private-person',
            }), zlib.compress(buffer.getvalue())))
            db.executemany('INSERT INTO motion_clips VALUES(?,?,30,?,?)', [
                (3,1,json.dumps({'training_eligible':False,'rights_confirmed':True}),zlib.compress(buffer.getvalue())),
                (4,1,json.dumps({'training_eligible':True,'rights_confirmed':False}),zlib.compress(buffer.getvalue())),
                (5,1,json.dumps({'training_eligible':False,'rights_confirmed':False}),zlib.compress(buffer.getvalue())),
            ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_import_publishes_coordinates_without_video_or_extra_consent(self):
        before = self.source.read_bytes()
        clip = read_clip(self.source, 2)
        row = import_clip(self.store, self.mod, clip, rights_confirmed=True)
        public = self.store.motion(row['id'])
        self.assertEqual(public['label'], 'Сәлем')
        np.testing.assert_array_equal(public['sequence'], self.array)
        self.assertEqual(public['metadata']['body_pose_status'], 'available')
        self.assertEqual(len(public['metadata']['body_pose_landmarks']), 56)
        self.assertNotIn('raw_video', public['metadata'])
        self.assertNotIn('signer_id', public['metadata'])
        self.assertEqual(row['source_status'], 'not_imported')
        self.assertFalse(row['training'])
        self.assertFalse(row['research'])
        self.assertEqual(len(self.store.gestures()), 1)
        self.assertEqual(self.source.read_bytes(), before)
        with self.assertRaises(DomainError):
            self.store.request_source_deletion(self.mod, row['id'])

    def test_repeat_import_is_idempotent_and_does_not_republish_withdrawn_material(self):
        clip = read_clip(self.source, 2)
        first = import_clip(self.store, self.mod, clip, rights_confirmed=True)
        second = import_clip(self.store, self.mod, clip, rights_confirmed=True)
        self.assertEqual(first['id'], second['id'])
        self.store.withdraw(self.mod, first['id'], 'Withdraw', first['revision'])
        import_clip(self.store, self.mod, clip, rights_confirmed=True)
        self.assertEqual(self.store.gestures(), [])

    def test_import_requires_moderator_and_explicit_rights(self):
        clip = read_clip(self.source, 2)
        for actor, rights in ((self.user, True), (self.mod, False)):
            with self.assertRaises(DomainError):
                import_clip(self.store, actor, clip, rights_confirmed=rights)
        self.assertEqual(self.store.gestures(), [])

    def test_invalid_coordinates_leave_no_submission(self):
        clip = read_clip(self.source, 2)
        clip['sequence'][0, 0] = np.nan
        with self.assertRaises(ValueError):
            import_clip(self.store, self.mod, clip, rights_confirmed=True)
        self.assertEqual(self.store.submissions(self.mod), [])

    def test_batch_selection_only_includes_quality_eligible_rights_confirmed_clips(self):
        before=self.source.read_bytes()
        selected,report=eligible_clip_ids(self.source)
        self.assertEqual(selected,[2])
        self.assertEqual(report,{'source_clips':4,'not_training_eligible':2,
            'rights_not_confirmed':2,'both_exclusions':1,'selected':1})
        self.assertEqual(self.source.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
