import re
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from core.models import AuditEvent, Family, FinancialRecord, Goal, Membership, Role
from core.templatetags.money import inr


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CentralTests(TestCase):
    def setUp(self):
        self.family = Family.objects.create(name='Test family')
        self.owner = get_user_model().objects.create_user(username='owner@example.test', email='owner@example.test', password='Synthetic-password-293!')
        Membership.objects.create(user=self.owner, family=self.family, role=Role.OWNER)
        self.client = Client(enforce_csrf_checks=True)
        token = self.token('/login/')
        self.client.post('/login/', {'username': self.owner.username, 'password': 'Synthetic-password-293!', 'csrfmiddlewaretoken': token})

    def token(self, path='/profile/'):
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', self.client.get(path).content.decode())[1]

    def post(self, path, data):
        return self.client.post(path, {**data, 'csrfmiddlewaretoken': self.token()})

    def finance_data(self, **values):
        return {'name': 'Savings', 'kind': 'asset', 'category': 'cash', 'amount': '123456.78',
                'valued_on': '2026-01-01', 'notes': '', 'revision': 1, **values}

    def goal_data(self, **values):
        return {'title': 'Education milestone', 'area': 'education', 'target_date': '2040-12-31',
                'progress': 20, 'status': 'active', 'notes': '', 'revision': 1, **values}

    def create_finance(self, **values):
        self.assertEqual(self.post('/finance/new/', self.finance_data(**values)).status_code, 302)
        return FinancialRecord.objects.latest('created_at')

    def create_goal(self, **values):
        self.assertEqual(self.post('/goals/new/', self.goal_data(**values)).status_code, 302)
        return Goal.objects.latest('created_at')

    def test_empty_dashboard_does_not_invent_financial_values(self):
        page = self.client.get('/')
        self.assertContains(page, 'Add your first record')
        self.assertNotContains(page, '₹0.00')
        self.assertEqual(self.client.get('/api/v1/summary/').json()['finance']['record_count'], 0)

    def test_money_totals_are_exact_and_liabilities_subtract(self):
        self.create_finance(amount='0.10')
        self.create_finance(amount='0.20')
        self.create_finance(kind='liability', category='loan', amount='0.15')
        data = self.client.get('/api/v1/summary/').json()
        self.assertEqual(data['currency'], 'INR')
        self.assertEqual(data['finance']['assets_paise'], '30')
        self.assertEqual(data['finance']['liabilities_paise'], '15')
        self.assertEqual(data['finance']['net_worth_paise'], '15')
        self.assertContains(self.client.get('/'), '₹0.15')

    def test_negative_net_worth_and_indian_formatting(self):
        self.create_finance(kind='liability', category='loan', amount='100000.01')
        self.assertContains(self.client.get('/finance/'), '−₹1,00,000.01')
        self.assertEqual(inr(123456789012345), '₹12,34,56,78,90,123.45')
        self.assertEqual(inr(-1), '−₹0.01')

    def test_large_values_are_exact_and_round_trip_in_edit(self):
        record = self.create_finance(amount='9999999999999.99')
        self.assertEqual(record.value_paise, 999999999999999)
        response = self.client.get(f'/finance/{record.id}/edit/')
        self.assertContains(response, '9999999999999.99')
        self.assertEqual(self.client.get('/api/v1/summary/').json()['finance']['assets_paise'], '999999999999999')

    def test_rejects_invalid_money_dates_and_category(self):
        bad = [dict(amount='-1'), dict(amount='0.001'), dict(amount='NaN'), dict(amount='Infinity'),
               dict(amount='10000000000000'), dict(kind='asset', category='loan'),
               dict(kind='liability', category='cash'), dict(kind='invalid'),
               dict(valued_on=str(timezone.localdate()+timedelta(days=1))), dict(valued_on='bad-date'), dict(name='')]
        for values in bad:
            with self.subTest(values=values):
                self.assertEqual(self.post('/finance/new/', self.finance_data(**values)).status_code, 400)
        self.assertFalse(FinancialRecord.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action='finance.created').exists())

    def test_edit_is_persistent_and_rejects_stale_updates(self):
        record = self.create_finance()
        path = f'/finance/{record.id}/edit/'
        self.assertEqual(self.post(path, self.finance_data(amount='200')).status_code, 302)
        self.assertEqual(self.post(path, self.finance_data(amount='300')).status_code, 409)
        record.refresh_from_db()
        self.assertEqual(record.value_paise, 20000)
        self.assertEqual(record.revision, 2)
        self.assertEqual(AuditEvent.objects.filter(action='finance.updated').count(), 1)

    def test_archive_restore_recalculates_without_deleting(self):
        record = self.create_finance()
        path = f'/finance/{record.id}/archive/'
        self.assertEqual(self.client.get(path).status_code, 200)
        record.refresh_from_db()
        self.assertFalse(record.archived)
        self.assertEqual(self.post(path, {'revision': 1}).status_code, 302)
        self.assertEqual(self.client.get('/api/v1/summary/').json()['finance']['record_count'], 0)
        self.assertContains(self.client.get('/finance/?archived=1'), 'Savings')
        self.assertEqual(self.client.get(f'/finance/{record.id}/edit/').status_code, 404)
        self.assertEqual(self.post(f'/finance/{record.id}/restore/', {'revision': 1}).status_code, 409)
        self.assertEqual(self.post(f'/finance/{record.id}/restore/', {'revision': 2}).status_code, 302)
        self.assertEqual(self.client.get('/api/v1/summary/').json()['finance']['record_count'], 1)
        record.refresh_from_db()
        self.assertEqual(record.revision, 3)

    def test_mass_assignment_cannot_set_owner_family_archive_or_version(self):
        record = self.create_finance(family_id=999, archived=True, revision=88, value_paise=1, id=str(uuid4()))
        self.assertEqual(record.family_id, self.family.id)
        self.assertFalse(record.archived)
        self.assertEqual(record.revision, 1)
        self.assertEqual(record.value_paise, 12345678)

    def test_goal_progress_completion_overdue_and_paused(self):
        overdue = str(timezone.localdate()-timedelta(days=1))
        goal = self.create_goal(target_date=overdue)
        self.create_goal(title='Paused', target_date=overdue, status='paused')
        self.assertTrue(goal.overdue)
        data = self.client.get('/api/v1/summary/').json()['goals']
        self.assertEqual(data, {'active': 1, 'completed': 0, 'overdue': 1})
        result = self.post(f'/goals/{goal.id}/edit/', self.goal_data(progress=100))
        self.assertEqual(result.status_code, 302)
        goal.refresh_from_db()
        self.assertEqual(goal.status, 'completed')
        self.assertEqual(self.client.get('/api/v1/summary/').json()['goals'], {'active': 0, 'completed': 1, 'overdue': 0})

    def test_goal_validation_and_conflicts(self):
        for values in [dict(progress=-1), dict(progress=101), dict(progress='3.5'), dict(status='completed', progress=99), dict(area='unknown'), dict(title=''), dict(target_date='bad')]:
            self.assertEqual(self.post('/goals/new/', self.goal_data(**values)).status_code, 400)
        goal = self.create_goal()
        self.assertEqual(self.post(f'/goals/{goal.id}/edit/', self.goal_data(progress=40)).status_code, 302)
        self.assertEqual(self.post(f'/goals/{goal.id}/edit/', self.goal_data(progress=60)).status_code, 409)
        goal.refresh_from_db()
        self.assertEqual(goal.progress, 40)

    def test_goal_archive_restore_affects_dashboard(self):
        goal = self.create_goal()
        self.post(f'/goals/{goal.id}/archive/', {'revision': 1})
        self.assertEqual(self.client.get('/api/v1/summary/').json()['goals']['active'], 0)
        self.assertEqual(self.client.get(f'/goals/{goal.id}/edit/').status_code, 404)
        self.assertContains(self.client.get('/goals/?archived=1'), goal.title)
        self.post(f'/goals/{goal.id}/restore/', {'revision': 2})
        self.assertEqual(self.client.get('/api/v1/summary/').json()['goals']['active'], 1)

    def test_new_routes_remain_owner_only(self):
        outsider = Client()
        for path in ['/finance/', '/finance/new/', '/goals/', '/goals/new/', f'/finance/{uuid4()}/edit/', f'/goals/{uuid4()}/archive/']:
            self.assertRedirects(outsider.get(path), '/login/', fetch_redirect_response=False)
        self.assertEqual(outsider.get('/api/v1/summary/').status_code, 401)
        Membership.objects.update(role='adult')
        self.assertEqual(self.client.get('/api/v1/summary/').status_code, 401)

    def test_csrf_required_for_create_edit_archive_restore(self):
        record = self.create_finance()
        goal = self.create_goal()
        for path in ['/finance/new/', '/goals/new/', f'/finance/{record.id}/edit/', f'/finance/{record.id}/archive/', f'/finance/{record.id}/restore/', f'/goals/{goal.id}/edit/', f'/goals/{goal.id}/archive/', f'/goals/{goal.id}/restore/']:
            self.assertEqual(self.client.post(path, {}).status_code, 403)
        self.assertEqual(self.post('/api/v1/summary/', {}).status_code, 405)

    def test_unknown_record_returns_404(self):
        for path in [f'/finance/{uuid4()}/edit/', f'/goals/{uuid4()}/archive/']:
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_atomic_audit_failure_rolls_back_create_and_update(self):
        with patch('core.central.AuditEvent.objects.create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.post('/finance/new/', self.finance_data())
        self.assertFalse(FinancialRecord.objects.exists())
        record = self.create_finance()
        with patch('core.central.AuditEvent.objects.create', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.post(f'/finance/{record.id}/edit/', self.finance_data(amount='9'))
        record.refresh_from_db()
        self.assertEqual(record.value_paise, 12345678)

    def test_private_values_do_not_enter_audit(self):
        self.create_finance(name='Private bank', notes='Private note')
        self.create_goal(title='Private ambition')
        response = self.client.get('/api/v1/audit/')
        for text in ['Private bank', 'Private note', 'Private ambition', '123456']:
            self.assertNotContains(response, text)
        self.assertContains(response, 'finance.created')

    def test_escaping_and_pagination(self):
        self.create_goal(title='<script>alert(1)</script>')
        self.assertContains(self.client.get('/goals/'), '&lt;script&gt;')
        self.assertNotContains(self.client.get('/goals/'), '<script>')
        FinancialRecord.objects.bulk_create([FinancialRecord(family=self.family, name=f'Record {i:02}', kind='asset', category='cash', value_paise=i, valued_on=date(2026, 1, 1)) for i in range(21)])
        self.assertContains(self.client.get('/finance/'), 'Page 1 of 2')
        self.assertContains(self.client.get('/finance/?page=2'), 'Record 20')
        self.assertNotContains(self.client.get('/finance/'), 'Record 20')

    def test_valuation_range_excludes_archive(self):
        first = self.create_finance(valued_on='2020-01-01')
        self.create_finance(valued_on='2026-01-01')
        self.post(f'/finance/{first.id}/archive/', {'revision': 1})
        summary = self.client.get('/api/v1/summary/').json()['finance']
        self.assertEqual(summary['oldest_valuation'], '2026-01-01')

    def test_database_rejects_invalid_financial_and_goal_states(self):
        for create in [
            lambda: FinancialRecord.objects.create(family=self.family, name='Bad', kind='asset', category='loan', value_paise=1, valued_on=date.today()),
            lambda: FinancialRecord.objects.create(family=self.family, name='Bad', kind='asset', category='cash', value_paise=-1, valued_on=date.today()),
            lambda: Goal.objects.create(family=self.family, title='Bad', area='finance', progress=101, status='active', target_date=date.today()),
            lambda: Goal.objects.create(family=self.family, title='Bad', area='finance', progress=20, status='completed', target_date=date.today()),
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                create()
