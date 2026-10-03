import base64
import io
import re
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from PIL import Image
from core.models import AuditEvent, Family, Membership, Role
from vault import gmail, storage
from vault.models import Document, FamilyPerson, GmailConnection, OAuthAttempt
from vault.services import ingest
from vault.sync import run_page, request_sync


def png(color='white'):
    stream = io.BytesIO()
    Image.new('RGB', (4, 4), color).save(stream, format='PNG')
    return stream.getvalue()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class VaultTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(VAULT_ROOT=self.temp.name, VAULT_KEY=Fernet.generate_key().decode(),
            VAULT_CLAMD_HOST='127.0.0.1', GMAIL_CLIENT_ID='synthetic', GMAIL_CLIENT_SECRET='synthetic',
            GMAIL_REDIRECT_URI='http://localhost/vault/gmail/callback/')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.scan = patch('vault.storage.scan').start()
        self.addCleanup(patch.stopall)
        self.family = Family.objects.create(name='Synthetic family')
        self.owner = get_user_model().objects.create_user(username='owner@example.test', password='Synthetic-password-293!')
        Membership.objects.create(user=self.owner, family=self.family, role=Role.OWNER)
        self.client = Client(enforce_csrf_checks=True)
        token = self.token('/login/')
        self.client.post('/login/', {'username': self.owner.username, 'password': 'Synthetic-password-293!', 'csrfmiddlewaretoken': token})

    def token(self, path='/profile/'):
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', self.client.get(path).content.decode())[1]

    def post(self, path, data=None):
        return self.client.post(path, {'csrfmiddlewaretoken': self.token(), **(data or {})})

    def upload(self, **values):
        return self.post('/vault/upload/', {'title': 'Private insurance', 'category': 'insurance', 'revision': 1,
            'file': SimpleUploadedFile('policy.png', png(), content_type='image/png'), **values})

    def doc(self):
        return ingest(family_id=1, data=png(), name='policy.png', category='insurance', actor=self.owner)[0]

    def connection(self, **values):
        return GmailConnection.objects.create(family=self.family, connected=True, requested=True,
            credentials=storage.seal({'refresh_token': 'synthetic-refresh'}), **values)

    def message(self, data=None, name='policy.png', subject='Insurance renewal'):
        return {'payload': {'headers': [{'name': 'Subject', 'value': subject}], 'parts': [
            {'filename': name, 'body': {'size': len(data or png()), 'data': base64.urlsafe_b64encode(data or png()).decode()}}]}}

    def test_upload_encrypted_at_rest_and_download_exact_bytes(self):
        self.assertEqual(self.upload().status_code, 302)
        doc = Document.objects.get()
        self.assertNotIn('Private insurance', doc.details)
        self.assertNotIn(png(), storage.object_path(doc.storage_key).read_bytes())
        response = self.client.get(f'/vault/{doc.pk}/download/')
        self.assertEqual(b''.join(response.streaming_content), png())
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertIn('sandbox', response['Content-Security-Policy'])
        self.assertTrue(AuditEvent.objects.filter(action='vault.downloaded').exists())
        self.assertContains(self.client.get('/vault/'), 'Private insurance')

    def test_duplicate_upload_and_archived_content_not_resaved(self):
        doc = self.doc()
        doc.archived = True
        doc.save()
        self.assertEqual(self.upload().status_code, 302)
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.enc'))), 1)
        doc.refresh_from_db()
        self.assertTrue(doc.archived)

    def test_anonymous_and_nonowner_cannot_access_routes(self):
        doc = self.doc()
        paths = ['/vault/', '/vault/upload/', '/vault/people/new/', '/vault/gmail/callback/',
                 f'/vault/{doc.pk}/download/', f'/vault/{doc.pk}/view/', f'/vault/{doc.pk}/edit/']
        anonymous = Client()
        for path in paths:
            self.assertRedirects(anonymous.get(path), '/login/', fetch_redirect_response=False)
        Membership.objects.filter(user=self.owner).update(role=Role.ADULT)
        for path in paths:
            self.assertRedirects(self.client.get(path), '/login/', fetch_redirect_response=False)

    def test_csrf_and_mutation_methods(self):
        for path in ['/vault/upload/', '/vault/refresh/', '/vault/gmail/connect/', '/vault/gmail/disconnect/']:
            self.assertEqual(self.client.post(path).status_code, 403)
        for path in ['/vault/refresh/', '/vault/gmail/connect/', '/vault/gmail/disconnect/']:
            self.assertEqual(self.client.get(path).status_code, 405)

    def test_wrong_key_and_tampered_content_fail_closed(self):
        doc = self.doc()
        with override_settings(VAULT_KEY=Fernet.generate_key().decode()):
            self.assertEqual(self.client.get(f'/vault/{doc.pk}/download/').status_code, 503)
            self.assertContains(self.client.get('/vault/'), 'temporarily unavailable')
        storage.object_path(doc.storage_key).write_bytes(b'corrupt')
        self.assertEqual(self.client.get(f'/vault/{doc.pk}/view/').status_code, 503)

    def test_storage_inside_repository_rejected(self):
        from django.conf import settings
        with override_settings(VAULT_ROOT=str(settings.BASE_DIR / 'private')):
            self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(Document.objects.exists())

    def test_edit_revision_and_member_validation(self):
        doc = self.doc()
        person = FamilyPerson.objects.create(family=self.family, name='Synthetic child')
        values = {'title': 'Updated', 'category': 'medical', 'person': person.pk, 'revision': 1,
                  'starred': True, 'expires_on': '2027-01-01', 'renew_on': '2026-12-01', 'notes': 'Synthetic'}
        self.assertEqual(self.post(f'/vault/{doc.pk}/edit/', values).status_code, 302)
        self.assertEqual(self.post(f'/vault/{doc.pk}/edit/', {**values, 'title': 'Stale'}).status_code, 409)
        doc.refresh_from_db()
        self.assertEqual(storage.unseal(doc.details)['title'], 'Updated')
        self.assertEqual(doc.person, person)
        self.assertTrue(doc.starred)
        person.archived = True
        person.save()
        self.assertEqual(self.post(f'/vault/{doc.pk}/edit/', {**values, 'revision': 2}).status_code, 400)

    def test_archive_restore_and_stale_requests(self):
        doc = self.doc()
        path = f'/vault/{doc.pk}/archive/'
        self.assertEqual(self.post(path, {'revision': 1}).status_code, 302)
        self.assertEqual(self.post(path, {'revision': 1}).status_code, 409)
        self.assertNotContains(self.client.get('/vault/'), 'policy.png')
        self.assertContains(self.client.get('/vault/?archived=1'), 'policy.png')
        self.assertEqual(self.post(path, {'revision': 2}).status_code, 302)
        self.assertEqual(Document.objects.get().revision, 3)

    def test_invalid_types_sizes_and_scanner_failure(self):
        for name, data in [('bad.html', b'<script>alert(1)</script>'), ('bad.png', b'not a PNG'), ('empty.pdf', b'')]:
            self.assertEqual(self.upload(file=SimpleUploadedFile(name, data)).status_code, 400)
        with override_settings(VAULT_MAX_BYTES=10):
            self.assertEqual(self.upload().status_code, 400)
        self.scan.side_effect = storage.VaultError('Scanner unavailable')
        self.assertEqual(self.upload().status_code, 400)
        self.assertFalse(Document.objects.exists())

    def test_pdf_validation(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        self.assertEqual(storage.validate(stream.getvalue(), 'test.pdf'), 'application/pdf')
        writer.encrypt('test')
        encrypted = io.BytesIO()
        writer.write(encrypted)
        with self.assertRaises(storage.RejectedFile):
            storage.validate(encrypted.getvalue(), 'private.pdf')

    def test_oauth_state_pkce_scope_expiry_and_replay(self):
        response = self.post('/vault/gmail/connect/')
        params = parse_qs(urlsplit(response.url).query)
        self.assertEqual(params['scope'], [gmail.SCOPE])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertNotIn('synthetic-refresh', response.url)
        pending = storage.unseal(OAuthAttempt.objects.get().pending)
        with patch('vault.gmail.exchange', return_value={'refresh_token': 'synthetic-refresh'}) as exchange:
            path = '/vault/gmail/callback/?code=synthetic&state=' + pending['state']
            self.assertEqual(self.client.get(path).status_code, 302)
            self.assertEqual(self.client.get(path).status_code, 400)
            exchange.assert_called_once_with('synthetic', pending['verifier'])
        connection = GmailConnection.objects.get()
        self.assertNotIn('synthetic-refresh', connection.credentials)
        self.assertTrue(connection.requested)
        self.post('/vault/gmail/connect/')
        attempt = OAuthAttempt.objects.get()
        state = storage.unseal(attempt.pending)
        state['created'] = time.time()-601
        attempt.pending = storage.seal(state)
        attempt.save()
        self.assertEqual(self.client.get('/vault/gmail/callback/?code=x&state='+state['state']).status_code, 400)

    def test_oauth_denied_and_bad_state_never_exchange(self):
        self.post('/vault/gmail/connect/')
        state = self.client.session['gmail_oauth']
        with patch('vault.gmail.exchange') as exchange:
            self.assertEqual(self.client.get('/vault/gmail/callback/?state=wrong&code=x').status_code, 400)
            self.post('/vault/gmail/connect/')
            state = self.client.session['gmail_oauth']
            self.assertEqual(self.client.get('/vault/gmail/callback/?state='+state+'&error=access_denied').status_code, 302)
            exchange.assert_not_called()
        self.assertFalse(GmailConnection.objects.exists())

    def test_oauth_client_failure_shows_safe_actionable_message(self):
        self.post('/vault/gmail/connect/')
        state = self.client.session['gmail_oauth']
        with patch('vault.gmail.exchange', side_effect=gmail.GmailError(401, 'invalid_client')):
            response = self.client.get('/vault/gmail/callback/', {'state': state, 'code': 'private-code'}, follow=True)
        self.assertContains(response, 'matching Web application client ID and secret')
        self.assertNotContains(response, 'private-code')
        self.assertFalse(GmailConnection.objects.exists())
        self.assertFalse(OAuthAttempt.objects.exists())

    def test_disconnect_clears_tokens_preserves_documents(self):
        self.doc()
        connection = self.connection()
        with patch('vault.gmail.revoke', return_value=False):
            response = self.post('/vault/gmail/disconnect/')
        self.assertEqual(response.status_code, 302)
        connection.refresh_from_db()
        self.assertFalse(connection.connected)
        self.assertEqual(connection.credentials, '')
        self.assertFalse(connection.requested)
        self.assertEqual(Document.objects.count(), 1)

    def test_refresh_rate_limit(self):
        connection = self.connection()
        connection.requested = False
        connection.last_attempt = timezone.now()
        connection.save()
        self.assertFalse(request_sync(1))
        connection.last_attempt -= timedelta(minutes=6)
        connection.save()
        self.assertTrue(request_sync(1))
        self.assertFalse(request_sync(1))

    @patch('vault.sync.GmailClient')
    def test_full_sync_and_incremental_duplicate_deduplication(self, client_type):
        connection = self.connection()
        client = client_type.return_value
        client.get.side_effect = [{'historyId': '100'}, {'messages': [{'id': 'm1'}]}]
        client.message.return_value = self.message()
        self.assertTrue(run_page())
        connection.refresh_from_db()
        self.assertEqual(connection.history_id, '100')
        self.assertFalse(connection.full_sync)
        self.assertEqual(connection.imported, 1)
        self.assertEqual(connection.status, 'ready')
        connection.requested = True
        connection.save()
        client.get.side_effect = [{'history': [{'messagesAdded': [{'message': {'id': 'm2'}}]}], 'historyId': '102'}]
        run_page()
        connection.refresh_from_db()
        self.assertEqual(connection.history_id, '102')
        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(Document.objects.get().source, 'gmail')

    @patch('vault.sync.GmailClient')
    def test_pagination_persists_checkpoint_and_retries_failures(self, client_type):
        connection = self.connection()
        client = client_type.return_value
        client.get.side_effect = [{'historyId': '100'}, {'messages': [{'id': 'a'}], 'nextPageToken': 'private-page'}]
        client.message.return_value = self.message()
        run_page()
        connection.refresh_from_db()
        self.assertNotEqual(connection.page_token, 'private-page')
        self.assertEqual(storage.unseal(connection.page_token), 'private-page')
        self.assertTrue(connection.requested)
        client.get.side_effect = gmail.GmailError(503)
        run_page()
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'error')
        self.assertEqual(storage.unseal(connection.page_token), 'private-page')
        self.assertEqual(storage.read_object(Document.objects.get()), png())
        connection.requested = True
        connection.save()
        client.get.side_effect = [{'messages': [{'id': 'a'}]}]
        run_page()
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'ready')
        self.assertEqual(connection.history_id, '100')
        self.assertEqual(Document.objects.count(), 1)

    @patch('vault.sync.GmailClient')
    def test_expired_history_restarts_full_import(self, client_type):
        connection = self.connection(full_sync=False, history_id='old')
        client_type.return_value.get.side_effect = gmail.GmailError(404)
        run_page()
        connection.refresh_from_db()
        self.assertTrue(connection.full_sync)
        self.assertTrue(connection.requested)
        self.assertEqual(connection.status, 'queued')

    @patch('vault.sync.GmailClient')
    def test_unrelated_invalid_and_unsafe_attachments_are_not_saved(self, client_type):
        connection = self.connection()
        client = client_type.return_value
        client.get.side_effect = [{'historyId': '100'}, {'messages': [{'id': 'a'}, {'id': 'b'}, {'id': 'c'}]}]
        client.message.side_effect = [self.message(name='logo.png', subject='Hello'), self.message(data=b'bad'), self.message()]
        self.scan.side_effect = storage.RejectedFile('unsafe')
        run_page()
        connection.refresh_from_db()
        self.assertEqual(connection.status, 'ready')
        self.assertEqual(connection.skipped, 2)
        self.assertFalse(Document.objects.exists())

    @patch('vault.sync.GmailClient')
    def test_active_worker_lease_is_not_stolen(self, client_type):
        self.connection(lease_until=timezone.now()+timedelta(minutes=5))
        self.assertFalse(run_page())
        client_type.assert_not_called()

    @patch('vault.sync.GmailClient')
    def test_disconnect_during_fetch_cannot_restore_access_or_import(self, client_type):
        connection = self.connection()
        client = client_type.return_value
        client.get.side_effect = [{'historyId': '100'}, {'messages': [{'id': 'a'}]}]
        def disconnect(*args):
            GmailConnection.objects.filter(pk=1).update(connected=False, credentials='')
            return self.message()
        client.message.side_effect = disconnect
        run_page()
        self.assertFalse(Document.objects.exists())
        connection.refresh_from_db()
        self.assertEqual(connection.credentials, '')


class ScannerTests(TestCase):
    @override_settings(VAULT_CLAMD_HOST='127.0.0.1', VAULT_CLAMD_PORT=3310)
    def test_clamd_protocol_and_fail_closed(self):
        with patch('vault.storage.socket.create_connection') as connect:
            sock = connect.return_value.__enter__.return_value
            sock.recv.return_value = b'stream: OK\0'
            storage.scan(b'synthetic')
            self.assertEqual(sock.sendall.call_args_list[0].args[0], b'zINSTREAM\0')
            sock.recv.return_value = b'stream: Eicar FOUND\0'
            with self.assertRaises(storage.RejectedFile):
                storage.scan(b'synthetic')
            sock.recv.return_value = b'stream: scanner ERROR\0'
            with self.assertRaises(storage.VaultError):
                storage.scan(b'synthetic')
        with patch('vault.storage.socket.create_connection', side_effect=OSError):
            with self.assertRaises(storage.VaultError):
                storage.scan(b'synthetic')

    @override_settings(VAULT_CLAMD_HOST='')
    def test_no_scanner_is_an_error(self):
        with self.assertRaises(storage.VaultError):
            storage.scan(b'synthetic')
