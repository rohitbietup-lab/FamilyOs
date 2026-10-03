import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.gmail_client import load_web_client
from vault import gmail


class GmailSetupTests(SimpleTestCase):
    def load(self, document, uri=''):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'client.json'
            path.write_text(json.dumps(document), encoding='utf-8')
            return load_web_client(path, uri)

    def test_web_download_keeps_credentials_and_exact_callback_together(self):
        uri = 'http://localhost:8000/vault/gmail/callback/'
        self.assertEqual(self.load({'web': {'client_id': 'test-id', 'client_secret': 'test-secret',
                                            'redirect_uris': [uri]}}), ('test-id', 'test-secret', uri))

    def test_desktop_download_is_rejected_without_secret_disclosure(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'Web application') as caught:
            self.load({'installed': {'client_secret': 'private-canary'}})
        self.assertNotIn('private-canary', str(caught.exception))

    def test_redirect_must_match_and_multiple_redirects_need_selection(self):
        document = {'web': {'client_id': 'id', 'client_secret': 'secret',
                            'redirect_uris': ['https://one.test/vault/gmail/callback/',
                                              'https://two.test/vault/gmail/callback/']}}
        for uri in ('', 'https://one.test/vault/gmail/callback'):
            with self.subTest(uri=uri), self.assertRaises(ImproperlyConfigured):
                self.load(document, uri)
        self.assertEqual(self.load(document, document['web']['redirect_uris'][1])[2],
                         document['web']['redirect_uris'][1])

    def test_missing_malformed_and_oversized_files_have_safe_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'client.json'
            for body in (None, 'private-canary', 'x' * 65537, '[]', '{"web":{}}'):
                if body is not None:
                    path.write_text(body, encoding='utf-8')
                with self.subTest(body=body and body[:20]), self.assertRaises(ImproperlyConfigured) as caught:
                    load_web_client(path)
                self.assertNotIn('private-canary', str(caught.exception))

    def response(self, body, status=400):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.iter_content.return_value = [body]
        return response

    def test_token_error_exposes_only_allowlisted_guidance(self):
        for reason in ('invalid_client', 'invalid_grant', 'redirect_uri_mismatch',
                       'unauthorized_client', 'private-canary', {'secret': 'private-canary'}):
            body = json.dumps({'error': reason, 'error_description': 'private-canary'}).encode()
            with self.subTest(reason=reason), patch('vault.gmail.requests.request', return_value=self.response(body)):
                with self.assertRaises(gmail.GmailError) as caught:
                    gmail.request_json('POST', gmail.TOKEN_URL)
                self.assertNotIn('private-canary', str(caught.exception))
                self.assertEqual(caught.exception.status, 400)
                if isinstance(reason, str) and reason in gmail.GmailError.MESSAGES:
                    self.assertEqual(caught.exception.reason, reason)

    def test_bad_provider_responses_are_bounded_and_sanitized(self):
        for body in (b'private-canary', b'[]', b'x' * 65537):
            with self.subTest(size=len(body)), patch('vault.gmail.requests.request', return_value=self.response(body)):
                with self.assertRaises(gmail.GmailError) as caught:
                    gmail.request_json('POST', gmail.TOKEN_URL)
                self.assertNotIn('private-canary', str(caught.exception))

    def test_exchange_requires_readonly_scope_and_offline_token(self):
        for tokens, reason in (({'scope': None}, 'missing_scope'),
                               ({'scope': gmail.SCOPE, 'access_token': 'test'}, 'missing_refresh_token')):
            with patch('vault.gmail.request_json', return_value=tokens):
                with self.assertRaises(gmail.GmailError) as caught:
                    gmail.exchange('synthetic-code', 'synthetic-verifier')
                self.assertEqual(caught.exception.reason, reason)
