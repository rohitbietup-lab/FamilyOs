import re
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from core.models import AuditEvent, Family, Invitation, LoginThrottle, Membership, OwnerSession, Role

PASSWORD = 'test-only-long-passphrase-73!'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class FoundationTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='Example family')
        self.owner = get_user_model().objects.create_user(username='owner@example.test', email='owner@example.test', first_name='Example', password=PASSWORD)
        Membership.objects.create(user=self.owner, family=self.family, role=Role.OWNER)
        self.client = Client(enforce_csrf_checks=True)

    def token(self, client=None, path='/login/'):
        page = (client or self.client).get(path)
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())[1]

    def sign_in(self, client=None, username='owner@example.test', password=PASSWORD):
        client = client or self.client
        return client.post('/login/', {'username': username, 'password': password, 'csrfmiddlewaretoken': self.token(client)})

    def post(self, path, data=None, client=None):
        client = client or self.client
        return client.post(path, {**(data or {}), 'csrfmiddlewaretoken': self.token(client, '/profile/')})

    def test_login_logout_rotates_session_and_invalidates_cookie(self):
        session = self.client.session
        session['prelogin'] = True
        session.save()
        old_key = session.session_key
        self.assertEqual(self.sign_in().status_code, 302)
        key = self.client.cookies['familyos_session'].value
        self.assertNotEqual(old_key, key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertEqual(self.client.get('/api/v1/me/').json()['role'], 'owner')
        self.assertEqual(self.post('/logout/').status_code, 302)
        replay = Client()
        replay.cookies['familyos_session'] = key
        self.assertEqual(replay.get('/api/v1/me/').status_code, 401)
        self.assertFalse(OwnerSession.objects.exists())

    def test_anonymous_routes_deny_by_default(self):
        for route in ['/', '/profile/', '/family/', '/sessions/', '/future-page/']:
            self.assertRedirects(self.client.get(route), '/login/', fetch_redirect_response=False)
        for route in ['/api/v1/me/', '/api/v1/family/', '/api/v1/audit/', '/api/v1/invitations/', '/api/future/']:
            self.assertEqual(self.client.get(route).status_code, 401)

    def test_login_and_writes_require_csrf(self):
        self.assertEqual(self.client.post('/login/', {'username': self.owner.username, 'password': PASSWORD}).status_code, 403)
        self.sign_in()
        for route in ['/family/', '/profile/', '/logout/', '/sessions/revoke-all/', '/api/v1/family/']:
            self.assertEqual(self.client.post(route, {}).status_code, 403)
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertEqual(self.client.get('/sessions/revoke-all/').status_code, 405)

    def test_wrong_password_unknown_user_and_nonowner_rejected(self):
        adult = get_user_model().objects.create_user(username='adult@example.test', password=PASSWORD)
        Membership.objects.create(user=adult, family=self.family, role=Role.ADULT)
        for email, password in [('missing@example.test', PASSWORD), (self.owner.username, 'wrong'), (adult.username, PASSWORD)]:
            response = self.sign_in(username=email, password=password)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('familyos_session', response.cookies)
        self.assertFalse(OwnerSession.objects.exists())

    def test_inactive_owner_rejected(self):
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(self.sign_in().status_code, 400)

    def test_nonowner_cannot_bypass_via_valid_django_session(self):
        adult = get_user_model().objects.create_user(username='adult', password=PASSWORD, is_superuser=True)
        Membership.objects.create(user=adult, family=self.family, role=Role.ADULT)
        self.client.force_login(adult)
        OwnerSession.objects.create(user=adult, session_key=self.client.session.session_key, expires_at=timezone.now()+timedelta(hours=1))
        self.assertEqual(self.client.get('/api/v1/family/').status_code, 401)

    def test_membership_disabled_revokes_access(self):
        self.sign_in()
        Membership.objects.update(active=False)
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_idle_expiry(self):
        self.sign_in()
        OwnerSession.objects.update(last_seen_at=timezone.now()-timedelta(minutes=31))
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)
        self.assertFalse(OwnerSession.objects.exists())

    def test_absolute_expiry_even_with_recent_activity(self):
        self.sign_in()
        OwnerSession.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_database_session_expiry(self):
        self.sign_in()
        Session.objects.update(expire_date=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_revoke_another_session_and_all_sessions(self):
        other = Client(enforce_csrf_checks=True)
        self.sign_in(other)
        other_session = OwnerSession.objects.get()
        self.sign_in()
        self.assertEqual(self.post(f'/sessions/{other_session.id}/revoke/').status_code, 302)
        self.assertEqual(other.get('/api/v1/me/').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 200)
        self.sign_in(other)
        self.post('/sessions/revoke-all/')
        self.assertEqual(other.get('/api/v1/me/').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_revoke_current_session(self):
        self.sign_in()
        target = OwnerSession.objects.get()
        self.post(f'/sessions/{target.id}/revoke/')
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_cannot_revoke_someone_elses_session(self):
        other = get_user_model().objects.create_user(username='other')
        target = OwnerSession.objects.create(user=other, session_key='foreign-session', expires_at=timezone.now()+timedelta(hours=1))
        self.sign_in()
        self.assertEqual(self.post(f'/sessions/{target.id}/revoke/').status_code, 404)
        self.assertTrue(OwnerSession.objects.filter(pk=target.pk).exists())

    def test_password_change_invalidates_sessions(self):
        self.sign_in()
        self.owner.set_password('different-passphrase-849!')
        self.owner.save()
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)

    def test_throttle_shared_across_clients_and_can_expire(self):
        for _ in range(10):
            self.assertEqual(self.sign_in(password='wrong').status_code, 400)
        fresh = Client(enforce_csrf_checks=True)
        result = self.sign_in(fresh)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result['Retry-After'], '900')
        self.assertEqual(AuditEvent.objects.filter(action='auth.login_failed').count(), 10)
        LoginThrottle.objects.update(window_start=timezone.now()-timedelta(minutes=16))
        self.assertEqual(self.sign_in(fresh).status_code, 302)

    def test_global_throttle_bounds_distributed_attempts(self):
        for i in range(50):
            client = Client(enforce_csrf_checks=True, REMOTE_ADDR=f'192.0.2.{i}')
            self.assertEqual(self.sign_in(client, password='wrong').status_code, 400)
        self.assertEqual(self.sign_in(Client(enforce_csrf_checks=True, REMOTE_ADDR='198.51.100.1')).status_code, 429)

    def test_family_persistence_across_clients_and_conflict_detection(self):
        self.sign_in()
        result = self.post('/api/v1/family/', {'name': 'Updated family', 'mission': 'Plan together', 'revision': 1})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['revision'], 2)
        other = Client(enforce_csrf_checks=True)
        self.sign_in(other)
        self.assertEqual(other.get('/api/v1/family/').json()['name'], 'Updated family')
        conflict = self.post('/api/v1/family/', {'name': 'Stale edit', 'mission': '', 'revision': 1}, other)
        self.assertEqual(conflict.status_code, 409)
        self.family.refresh_from_db()
        self.assertEqual(self.family.name, 'Updated family')
        self.assertEqual(AuditEvent.objects.filter(action='family.updated').count(), 1)

    def test_input_validation_and_mass_assignment_protection(self):
        self.sign_in()
        invalid = self.post('/api/v1/family/', {'name': 'x'*101, 'mission': '', 'revision': 1})
        self.assertEqual(invalid.status_code, 400)
        self.post('/profile/', {'display_name': 'New name', 'is_superuser': 'true', 'email': 'attacker@example.test'})
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.first_name, 'New name')
        self.assertFalse(self.owner.is_superuser)
        self.assertEqual(self.owner.email, 'owner@example.test')

    def test_output_escaping_and_security_headers(self):
        self.sign_in()
        self.family.name = '<script>alert(1)</script>'
        self.family.save()
        result = self.client.get('/')
        self.assertContains(result, '&lt;script&gt;')
        self.assertNotContains(result, '<script>')
        self.assertEqual(result['Cache-Control'], 'no-store')
        self.assertEqual(result['X-Frame-Options'], 'DENY')
        self.assertIn("default-src 'none'", result['Content-Security-Policy'])
        self.assertEqual(result['X-Content-Type-Options'], 'nosniff')

    def test_csrf_origin_validation(self):
        self.sign_in()
        token = self.token(path='/profile/')
        result = self.client.post('/profile/', {'display_name': 'Forged', 'csrfmiddlewaretoken': token}, HTTP_ORIGIN='https://attacker.example')
        self.assertEqual(result.status_code, 403)

    def test_login_redirect_cannot_leave_site(self):
        token = self.token()
        result = self.client.post('/login/?next=https://attacker.example', {'username': self.owner.username, 'password': PASSWORD, 'csrfmiddlewaretoken': token})
        self.assertEqual(result['Location'], '/')

    def test_enrollment_and_integrations_absent(self):
        self.sign_in()
        self.assertEqual(self.client.get('/api/v1/invitations/').status_code, 403)
        self.assertEqual(self.post('/api/v1/invitations/', {'email': 'invite@example.test'}).status_code, 403)
        for route in ['/signup/', '/register/', '/admin/', '/api/v1/gmail/', '/api/v1/vault/']:
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertFalse(Invitation.objects.exists())

    def test_database_constraints(self):
        for create in [
            lambda: Family.objects.create(id=2, name='Another family'),
            lambda: Membership.objects.create(user=get_user_model().objects.create_user(username='second'), family=self.family, role=Role.OWNER),
            lambda: Invitation.objects.create(family=self.family, email='x@example.test', role=Role.ADULT, status='pending'),
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()

    def test_audit_api_excludes_credentials_and_login_attempt_data(self):
        self.sign_in()
        result = self.client.get('/api/v1/audit/')
        self.assertContains(result, 'auth.login')
        self.assertNotContains(result, PASSWORD)
        self.assertNotContains(result, self.client.session.session_key)
        self.assertNotContains(result, self.owner.email)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_secure_cookie_attributes(self):
        result = self.sign_in()
        cookie = result.cookies['familyos_session']
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')

    def test_family_write_rolls_back_if_audit_fails(self):
        self.sign_in()
        with patch('core.views.audit', side_effect=RuntimeError('simulated audit failure')):
            with self.assertRaises(RuntimeError):
                self.post('/api/v1/family/', {'name': 'Unsaved change', 'mission': '', 'revision': 1})
        self.family.refresh_from_db()
        self.assertEqual(self.family.name, 'Example family')
        self.assertEqual(self.family.revision, 1)

    def test_prune_preserves_active_session_and_audit(self):
        self.sign_in()
        active = OwnerSession.objects.get()
        expired_client = Client(enforce_csrf_checks=True)
        self.sign_in(expired_client)
        expired = OwnerSession.objects.exclude(pk=active.pk).get()
        OwnerSession.objects.filter(pk=expired.pk).update(last_seen_at=timezone.now()-timedelta(hours=1))
        call_command('prune_sessions', stdout=StringIO())
        self.assertTrue(OwnerSession.objects.filter(pk=active.pk).exists())
        self.assertFalse(Session.objects.filter(session_key=expired.session_key).exists())
        self.assertEqual(AuditEvent.objects.filter(action='auth.login').count(), 2)

    def test_backup_rejects_repository_destination(self):
        from django.conf import settings
        with self.assertRaises(CommandError):
            call_command('backup_database', str(settings.BASE_DIR / 'unsafe-backup.sqlite3'))

    def test_untrusted_host_rejected(self):
        self.assertEqual(self.client.get('/login/', HTTP_HOST='attacker.example').status_code, 400)


class BootstrapTests(TestCase):
    def bootstrap(self):
        call_command('bootstrap_owner', email='OWNER@example.test', name='Example', family='Example family', stdout=StringIO())

    def test_bootstrap_hashes_password_and_cannot_replace_owner(self):
        with patch('core.management.commands.bootstrap_owner.getpass', return_value=PASSWORD):
            self.bootstrap()
        owner = get_user_model().objects.get()
        self.assertTrue(owner.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(check_password(PASSWORD, owner.password))
        self.assertEqual(owner.username, 'owner@example.test')
        self.assertFalse(owner.is_superuser)
        self.assertEqual(Membership.objects.get().role, Role.OWNER)
        with self.assertRaises(CommandError):
            self.bootstrap()

    def test_weak_or_mismatched_password_creates_nothing(self):
        for passwords in [('123', '123'), (PASSWORD, 'different')]:
            with patch('core.management.commands.bootstrap_owner.getpass', side_effect=passwords):
                with self.assertRaises(CommandError):
                    self.bootstrap()
        self.assertFalse(Family.objects.exists())
        self.assertFalse(get_user_model().objects.exists())
