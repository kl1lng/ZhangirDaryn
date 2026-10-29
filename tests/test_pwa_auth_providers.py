import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.auth import verify
from backend.settings import Settings


class AuthProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_unknown_auth_provider(self):
        with self.assertRaisesRegex(ValueError, 'DOSYM_AUTH_PROVIDER'):
            Settings(data_dir=Path(self.tmp.name), auth_provider='facebook')

    @patch.dict('os.environ', {'DOSYM_SIGNING_KEY': 's' * 40})
    def test_google_production_does_not_require_supabase_credentials(self):
        settings = Settings(
            data_dir=Path(self.tmp.name), environment='production', auth_provider='google',
            storage='drive', database_url='postgresql://db.example/dosym',
            google_client_id='client-id', google_client_secret='client-secret',
            google_redirect_uri='https://api.example/auth/google/callback',
            frontend_origin='https://dosym.example', origins=['https://dosym.example'],
            signing_key='s' * 40,
        )
        self.assertEqual(settings.auth_provider, 'google')

    def test_supabase_production_still_requires_supabase_credentials(self):
        with self.assertRaisesRegex(ValueError, 'Supabase'):
            Settings(
                data_dir=Path(self.tmp.name), environment='production', auth_provider='supabase',
                storage='drive', database_url='postgresql://db.example/dosym',
                signing_key='s' * 40,
            )


class GoogleAuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            data_dir=Path(self.tmp.name), auth_provider='google',
            google_client_id='dosym-client-id', google_client_secret='dosym-client-secret',
            google_redirect_uri='http://127.0.0.1:8765/auth/google/callback',
            frontend_origin='http://127.0.0.1:3000',
            origins=['http://127.0.0.1:3000'], moderator_email='moderator@example.com',
        )
        self.client = TestClient(create_app(self.settings), client=('127.0.0.1', 50000))

    def tearDown(self):
        self.tmp.cleanup()

    def test_auth_config_reports_google_provider(self):
        response = self.client.get('/auth/config')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['auth_provider'], 'google')
        self.assertTrue(response.json()['google_configured'])

    def test_start_requests_identity_scopes_and_signed_nonce(self):
        response = self.client.get('/auth/google/start', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(query['client_id'], ['dosym-client-id'])
        self.assertEqual(query['redirect_uri'], [self.settings.google_redirect_uri])
        self.assertEqual(query['scope'], ['openid email profile'])
        self.assertNotIn('drive', query['scope'][0].lower())
        state = verify(self.settings, query['state'][0], 'google-oauth-state')
        self.assertEqual(state['nonce'], query['nonce'][0])

    @patch('backend.api.verify_google_id_token')
    @patch('backend.auth.httpx.post')
    def test_callback_issues_session_for_verified_google_identity(self, post, verify_token):
        start = self.client.get('/auth/google/start', follow_redirects=False)
        query = parse_qs(urlsplit(start.headers['location']).query)
        state = verify(self.settings, query['state'][0], 'google-oauth-state')
        response_from_google = Mock()
        response_from_google.json.return_value = {'id_token': 'opaque-id-token'}
        post.return_value = response_from_google
        verify_token.return_value = {
            'sub': 'stable-google-subject', 'email': 'participant@example.com',
            'email_verified': True, 'name': 'Participant', 'nonce': state['nonce'],
        }

        callback = self.client.get('/auth/google/callback', params={
            'code': 'one-time-code', 'state': query['state'][0],
        }, follow_redirects=False)

        self.assertEqual(callback.status_code, 303)
        location = urlsplit(callback.headers['location'])
        self.assertEqual(location.scheme + '://' + location.netloc, self.settings.frontend_origin)
        self.assertEqual(location.path, '/auth/callback')
        session_token = parse_qs(location.fragment)['token'][0]
        me = self.client.get('/me', headers={'Authorization': 'Bearer ' + session_token})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()['id'], 'google:stable-google-subject')
        self.assertEqual(me.json()['role'], 'user')
        self.assertEqual(me.json()['email'], 'participant@example.com')
        post.assert_called_once()
        verify_token.assert_called_once_with('opaque-id-token', 'dosym-client-id')

    @patch('backend.api.verify_google_id_token')
    @patch('backend.auth.httpx.post')
    def test_callback_rejects_nonce_mismatch_without_creating_session(self, post, verify_token):
        start = self.client.get('/auth/google/start', follow_redirects=False)
        query = parse_qs(urlsplit(start.headers['location']).query)
        response_from_google = Mock()
        response_from_google.json.return_value = {'id_token': 'opaque-id-token'}
        post.return_value = response_from_google
        verify_token.return_value = {
            'sub': 'attacker-subject', 'email': 'participant@example.com',
            'email_verified': True, 'name': 'Participant', 'nonce': 'wrong-nonce',
        }

        callback = self.client.get('/auth/google/callback', params={
            'code': 'one-time-code', 'state': query['state'][0],
        }, follow_redirects=False)

        self.assertEqual(callback.status_code, 303)
        location = urlsplit(callback.headers['location'])
        self.assertEqual(parse_qs(location.query)['error'], ['google_login_failed'])
        self.assertEqual(location.fragment, '')
        self.assertEqual(self.client.get('/me').status_code, 401)

    def test_callback_rejects_invalid_state(self):
        callback = self.client.get('/auth/google/callback', params={
            'code': 'one-time-code', 'state': 'forged',
        }, follow_redirects=False)
        self.assertEqual(callback.status_code, 303)
        location = urlsplit(callback.headers['location'])
        self.assertEqual(parse_qs(location.query)['error'], ['google_login_failed'])
        self.assertEqual(location.fragment, '')


if __name__ == '__main__':
    unittest.main()
