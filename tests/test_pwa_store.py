import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.store import Store, DomainError


class PublicWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'public.sqlite3'
        self.store = Store(str(self.path))
        self.user = self.store.user('user-1', 'user@example.test', 'Автор')
        self.other = self.store.user('user-2', 'other@example.test', 'Другой')
        self.mod = self.store.user('mod-1', 'mod@example.test', 'Модератор', moderator=True)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, actor=None, key='one'):
        row = self.store.create_submission(actor or self.user, label='Сәлем', language='kk-KZ',
            filename='test.mp4', size=1024, mime='video/mp4', rights=True, training=True,
            idempotency_key='test-key-' + key)
        return self.store.complete_upload(actor or self.user, row['id'], 'local:test', {'fps': 30})

    def artifact(self, submission):
        job = self.store.claim_job('test-worker')
        self.assertEqual(job['submission_id'], submission['id'])
        self.store.finish_job(job['id'], job['lease_token'], np.ones((5, 162), dtype=np.float32),
                              {'fps': 30, 'training_eligible': True, 'signer_id': 'person-a'})

    def test_user_waits_and_moderator_upload_queues(self):
        row = self.upload()
        self.assertEqual((row['moderation_status'], row['processing_status']), ('pending', 'not_started'))
        self.assertIsNone(self.store.claim_job('worker'))
        trusted = self.upload(self.mod)
        self.assertEqual((trusted['moderation_status'], trusted['processing_status']), ('approved', 'queued'))

    def test_research_consent_is_separate_and_defaults_off(self):
        row=self.store.create_submission(self.user,label='Исследование',language='kk-KZ',filename='test.mp4',
            size=1024,mime='video/mp4',rights=True,training=True,idempotency_key='test-research-opt-out')
        self.assertEqual(row['training'],1)
        self.assertEqual(row['research'],0)
        opted=self.store.create_submission(self.user,label='Исследование 2',language='kk-KZ',filename='test.mp4',
            size=1024,mime='video/mp4',rights=True,training=False,research=True,idempotency_key='test-research-opt-in')
        self.assertEqual(opted['training'],0)
        self.assertEqual(opted['research'],1)

    def test_retry_cannot_change_consent_behind_same_idempotency_key(self):
        args=dict(label='Test',language='kk-KZ',filename='test.mp4',size=1024,mime='video/mp4',
            rights=True,training=False,idempotency_key='fixed-research-key')
        original=self.store.create_submission(self.user,**args)
        with self.assertRaises(DomainError) as error:
            self.store.create_submission(self.user,**{**args,'research':True})
        self.assertEqual(error.exception.status,409)
        self.assertEqual(self.store.submission(self.user,original['id'])['research'],0)

    def test_existing_database_migrates_with_research_disabled(self):
        import sqlite3
        db=sqlite3.connect(self.path)
        try:db.execute('ALTER TABLE pwa_submissions DROP COLUMN research');db.commit()
        finally:db.close()
        migrated=Store(str(self.path))
        row=migrated.create_submission(self.user,label='Legacy',language='kk-KZ',filename='test.mp4',
            size=1024,mime='video/mp4',rights=True,training=True,idempotency_key='test-legacy-research')
        self.assertEqual(row['research'],0)

    def test_idempotent_upload_does_not_create_second_submission(self):
        first = self.upload()
        again = self.upload()
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(len(self.store.submissions(self.user)), 1)

    def test_others_cannot_view_or_moderate(self):
        row = self.upload()
        with self.assertRaises(DomainError): self.store.submission(self.other, row['id'])
        with self.assertRaises(DomainError):
            self.store.decide(self.user, row['id'], 'approved', '', row['revision'])

    def test_double_approval_and_stale_revision(self):
        row = self.upload()
        approved = self.store.decide(self.mod, row['id'], 'approved', '', row['revision'])
        with self.assertRaises(DomainError):
            self.store.decide(self.mod, row['id'], 'approved', '', row['revision'])
        self.assertEqual(approved['processing_status'], 'queued')
        self.assertIsNotNone(self.store.claim_job('first'))
        self.assertIsNone(self.store.claim_job('second'))

    def test_rejection_requires_reason_and_never_trains(self):
        row = self.upload()
        with self.assertRaises(DomainError): self.store.decide(self.mod, row['id'], 'rejected', '', row['revision'])
        self.store.decide(self.mod, row['id'], 'rejected', 'Руки вне кадра', row['revision'])
        self.assertEqual(self.store.training_snapshot()['count'], 0)
        self.assertIsNone(self.store.claim_job('worker'))

    def test_coordinates_survive_source_deletion_and_service_restart(self):
        row = self.upload(self.mod)
        self.artifact(row)
        with self.assertRaises(DomainError): self.store.request_source_deletion(self.mod, row['id'])
        self.store.mark_backed_up(row['id'])
        self.store.request_source_deletion(self.mod, row['id'])
        self.store.finish_source_deletion(row['id'])
        restarted = Store(str(self.path))
        result = restarted.motion(row['id'])
        np.testing.assert_array_equal(np.asarray(result['sequence']), np.ones((5, 162)))
        self.assertEqual(restarted.training_snapshot()['count'], 1)
        self.assertEqual(restarted.submission(self.mod, row['id'])['source_status'], 'deleted')

    def test_invalid_array_never_becomes_ready(self):
        row = self.upload(self.mod)
        job = self.store.claim_job('worker')
        with self.assertRaises(ValueError):
            self.store.finish_job(job['id'], job['lease_token'], np.full((5,162), np.nan), {'fps':30})
        self.assertEqual(self.store.gestures(), [])

    def test_expired_lease_is_reclaimed_and_stale_worker_cannot_write(self):
        row = self.upload(self.mod)
        old = self.store.claim_job('old', now=10, lease_seconds=1)
        fresh = self.store.claim_job('new', now=12)
        self.assertEqual(old['id'], fresh['id'])
        with self.assertRaises(DomainError):
            self.store.finish_job(old['id'], old['lease_token'], np.ones((5,162)), {'fps':30})

    def test_public_catalog_contains_only_ready_approved(self):
        row = self.upload(self.mod)
        self.assertEqual(self.store.gestures(), [])
        self.artifact(row)
        self.assertEqual(len(self.store.gestures()), 1)
        self.upload(self.user)
        self.assertEqual(len(self.store.gestures()), 1)

    def test_training_waits_for_classes_and_independent_signers(self):
        row = self.upload(self.mod)
        self.artifact(row)
        snap = self.store.training_snapshot()
        self.assertFalse(snap['eligible'])
        self.assertTrue(snap['reason'])

    def test_database_reopen_does_not_elevate_role(self):
        self.store.user('user-1', 'user@example.test', 'Новое имя')
        self.assertEqual(self.store.user('user-1', 'user@example.test', 'Автор')['role'], 'user')

    def test_withdrawal_removes_public_motion_and_training_without_erasing_coordinates(self):
        row=self.upload(self.mod);self.artifact(row)
        current=self.store.submission(self.mod,row['id'])
        withdrawn=self.store.withdraw(self.mod,row['id'],'Запись отозвана',current['revision'])
        self.assertEqual(withdrawn['moderation_status'],'rejected')
        self.assertEqual(self.store.gestures(),[])
        self.assertEqual(self.store.training_snapshot()['count'],0)
        with self.assertRaises(DomainError):self.store.motion(row['id'])
        with self.store.transaction() as db:
            self.assertIsNotNone(db.execute('SELECT checksum FROM pwa_artifacts WHERE submission_id=?',(row['id'],)).fetchone())

    def test_withdrawal_cancels_running_extraction(self):
        row=self.upload(self.mod);job=self.store.claim_job('worker')
        current=self.store.submission(self.mod,row['id'])
        self.store.withdraw(self.mod,row['id'],'Отозвано',current['revision'])
        with self.assertRaises(DomainError):
            self.store.finish_job(job['id'],job['lease_token'],np.ones((5,162)),{'fps':30})


if __name__ == '__main__': unittest.main()
