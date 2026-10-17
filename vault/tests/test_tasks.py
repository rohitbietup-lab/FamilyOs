import re
import tempfile
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from core.models import AuditEvent, Family, Membership, Role
from vault.models import DocumentTask, FamilyPerson, TaskCompletion
from vault.services import ingest
from vault.storage import seal, unseal
from vault.tasks import create_document_task, next_due, task_today
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

    def test_manual_task_assignment_and_recurrence_validation(self):
        member=FamilyPerson.objects.create(family=self.family,name='Synthetic member')
        data={'title':'Synthetic responsibility','notes':'Private canary','revision':1,'due_on':'2026-10-25',
              'assignee':str(member.pk),'recurrence':'weekly','remind_days':3,'csrfmiddlewaretoken':self.token()}
        self.assertEqual(self.client.post('/tasks/new/',data).status_code,302)
        task=DocumentTask.objects.get()
        self.assertIsNone(task.source_document_id)
        self.assertEqual(task.assignee,member)
        self.assertNotIn('Private canary',task.details)
        self.assertEqual(self.client.post('/tasks/new/',{**data,'due_on':''}).status_code,400)
        member.archived=True
        member.save()
        self.assertEqual(self.client.post('/tasks/new/',data).status_code,400)
        self.assertEqual(DocumentTask.objects.count(),1)
        self.assertContains(self.client.get('/tasks/'),'Manually added task')

    def test_monthly_completion_preserves_anchor_and_records_each_occurrence(self):
        task=self.task()
        task.due_on=date(2027,1,31)
        task.recurrence='monthly'
        task.recurrence_day=31
        task.save()
        url=f'/tasks/{task.pk}/complete/'
        token=self.token()
        data={'completed':'1','revision':1,'csrfmiddlewaretoken':token}
        self.assertEqual(self.client.post(url,data).status_code,302)
        task.refresh_from_db()
        self.assertEqual(task.due_on,date(2027,2,28))
        self.assertFalse(task.completed)
        self.assertEqual(self.client.post(url,data).status_code,409)
        self.assertEqual(self.client.post(url,{**data,'revision':2}).status_code,302)
        task.refresh_from_db()
        self.assertEqual(task.due_on,date(2027,3,31))
        self.assertEqual(TaskCompletion.objects.filter(task=task).count(),2)
        self.assertEqual(set(task.completions.values_list('scheduled_on',flat=True)),{date(2027,1,31),date(2027,2,28)})

    def test_yearly_leap_day_and_weekly_dates(self):
        task=DocumentTask(due_on=date(2024,2,29),recurrence='yearly',recurrence_day=29)
        self.assertEqual(next_due(task),date(2025,2,28))
        task.due_on=date(2027,2,28)
        self.assertEqual(next_due(task),date(2028,2,29))
        task.recurrence='weekly'
        self.assertEqual(next_due(task),date(2027,3,7))

    def test_reminders_respect_dates_lead_days_and_completed_status(self):
        today=task_today()
        for kind,offset,lead,completed in [('past',-1,0,False),('today',0,0,False),('soon',3,3,False),('later',4,3,False),('done',-2,0,True)]:
            DocumentTask.objects.create(family=self.family,kind=kind,due_on=today+timedelta(days=offset),
                remind_days=lead,completed=completed,details=seal({'title':kind,'notes':'','evidence':''}))
        response=self.client.get('/tasks/?due=overdue')
        self.assertEqual(response.context['reminders']['overdue'],1)
        self.assertEqual(response.context['reminders']['today'],1)
        self.assertEqual(response.context['reminders']['count'],3)
        self.assertEqual(response.context['page'].paginator.count,1)
        self.assertEqual(self.client.get('/tasks/?due=today').context['page'].paginator.count,1)
        self.assertContains(self.client.get('/'),'Tasks and reminders')

    def test_task_day_uses_configured_timezone(self):
        with override_settings(TASK_TIME_ZONE='Asia/Kolkata'), patch('vault.tasks.timezone.now',return_value=datetime(2026,10,17,20,0,tzinfo=datetime_timezone.utc)):
            self.assertEqual(task_today(),date(2026,10,18))

    def test_edit_notes_does_not_lose_month_end_anchor(self):
        task=self.task()
        task.due_on=date(2027,2,28)
        task.recurrence='monthly'
        task.recurrence_day=31
        task.save()
        data={'title':'Updated','notes':'Notes','due_on':'2027-02-28','recurrence':'monthly','revision':1,'csrfmiddlewaretoken':self.token()}
        self.assertEqual(self.client.post(f'/tasks/{task.pk}/edit/',data).status_code,302)
        task.refresh_from_db()
        self.assertEqual(task.recurrence_day,31)
