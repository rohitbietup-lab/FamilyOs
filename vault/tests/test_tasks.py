import re
import tempfile
from datetime import date
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from core.models import AuditEvent, Family, Membership, Role
from vault.models import DocumentTask
from vault.services import ingest
from vault.storage import unseal
from vault.tasks import create_document_task
from vault.tests.test_vault import png


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DocumentTaskTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = override_settings(VAULT_ROOT=self.temp.name, VAULT_KEY=Fernet.generate_key().decode())
        self.config.enable()
        self.addCleanup(self.config.disable)
        self.scan = patch('vault.storage.scan').start()
        self.addCleanup(patch.stopall)
        self.family = Family.objects.create(name='Synthetic family')
        self.user = get_user_model().objects.create_user(username='owner@test.example', password='Synthetic-password-293!')
        Membership.objects.create(user=self.user, family=self.family, role=Role.OWNER)
        self.doc = ingest(family_id=self.family.pk, data=png(), name='policy.png', category='insurance')[0]
        self.client = Client(enforce_csrf_checks=True)
        token = self.token('/login/')
        self.client.post('/login/', {'username': self.user.username, 'password':'Synthetic-password-293!', 'csrfmiddlewaretoken':token})

    def token(self, path='/profile/'):
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', self.client.get(path).content.decode())[1]

    def task(self):
        return create_document_task(document=self.doc, kind='review-policy', title='Review synthetic policy',
            notes='Confirm renewal; an old document does not establish current coverage.', evidence='Synthetic expiry date',
            source_page=1, source_date=date(2026,7,31))[0]

    def test_encrypted_idempotent_creation_keeps_source_date_separate_from_deadline(self):
        task = self.task()
        self.assertEqual(self.task().pk, task.pk)
        self.assertEqual(DocumentTask.objects.count(), 1)
        self.assertNotIn('synthetic policy', task.details)
        self.assertIsNone(task.due_on)
        self.assertEqual(task.source_date, date(2026,7,31))
        self.assertEqual(AuditEvent.objects.filter(action='task.created').count(), 1)
        response = self.client.get('/tasks/')
        self.assertContains(response, 'Review synthetic policy')
        self.assertContains(response, '#page=1')
        self.assertContains(response, 'Not set')

    def test_tasks_require_owner_and_csrf_and_post_for_completion(self):
        task = self.task()
        url = f'/tasks/{task.pk}/complete/'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'completed':'1','revision':1}).status_code,403)
        self.assertRedirects(Client().get('/tasks/'), '/login/', fetch_redirect_response=False)
        Membership.objects.filter(user=self.user).update(role=Role.ADULT)
        self.assertRedirects(self.client.get('/tasks/'), '/login/', fetch_redirect_response=False)

    def test_completion_reopen_and_stale_revision(self):
        task = self.task()
        url = f'/tasks/{task.pk}/complete/'
        data = {'revision':1,'completed':'1','csrfmiddlewaretoken':self.token()}
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,409)
        self.assertNotContains(self.client.get('/tasks/'),'Review synthetic policy')
        self.assertContains(self.client.get('/tasks/?completed=1'),'Review synthetic policy')
        self.assertEqual(self.client.post(url,{**data,'revision':2,'completed':'0'}).status_code,302)
        task.refresh_from_db()
        self.assertFalse(task.completed)

    def test_edit_preserves_evidence_and_requires_current_revision(self):
        task = self.task()
        url = f'/tasks/{task.pk}/edit/'
        data={'title':'Updated review','notes':'Confirmed next action','due_on':'2026-10-25','revision':1,'csrfmiddlewaretoken':self.token()}
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,409)
        task.refresh_from_db()
        self.assertEqual(unseal(task.details)['evidence'],'Synthetic expiry date')
        self.assertEqual(task.due_on,date(2026,10,25))
        self.assertNotIn('Updated review',task.details)

    def test_unreadable_task_details_fail_closed(self):
        task=self.task()
        with override_settings(VAULT_KEY=Fernet.generate_key().decode()):
            self.assertContains(self.client.get('/tasks/'),'Task temporarily unavailable')
            self.assertEqual(self.client.get(f'/tasks/{task.pk}/edit/').status_code,503)

    def test_archived_sources_are_not_generated(self):
        self.doc.archived=True
        self.doc.save()
        with self.assertRaises(ValueError):
            self.task()
