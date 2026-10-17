import re
from datetime import timedelta
from copy import copy
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from core.enrollment import EnrollmentError, issue_invitation, accept_invitation, enrollment_ready
from core.models import Invitation, Membership, OwnerSession, Role
from vault.models import FamilyPerson, DocumentReadGrant
from vault.grants import set_document_grant
from vault.storage import seal
from vault.tasks import create_document_task
from vault.tests import test_vault as vault_fixtures


@override_settings(FAMILY_ENROLLMENT_ENABLED=True,PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EnrollmentTests(TestCase):
    token=vault_fixtures.VaultTests.token
    post=vault_fixtures.VaultTests.post
    doc=vault_fixtures.VaultTests.doc

    def setUp(self):
        vault_fixtures.VaultTests.setUp(self)
        self.person=FamilyPerson.objects.create(family=self.family,name='Synthetic adult')
        self.adult=get_user_model().objects.create_user(username='adult@example.test',email='adult@example.test',password='Synthetic-password-293!')
        self.member=Membership.objects.create(family=self.family,user=self.adult,role=Role.ADULT,person=self.person)
        self.adult_client=Client(enforce_csrf_checks=True)
        self.login(self.adult_client,'adult@example.test')
        self.owner_member=self.owner.membership

    def login(self,client,email):
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',client.get('/login/').content.decode())[1]
        return client.post('/login/',{'username':email,'password':'Synthetic-password-293!','csrfmiddlewaretoken':token})

    def adult_post(self,path,values):
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',self.adult_client.get('/profile/').content.decode())[1]
        return self.adult_client.post(path,{**values,'csrfmiddlewaretoken':token})

    def assigned(self):
        doc=self.doc()
        doc.details=seal({'title':'PRIVATE-DOCUMENT-CANARY','filename':'policy.png'})
        doc.save()
        task,_=create_document_task(document=doc,kind='assigned',title='Assigned review',notes='Shared task notes',evidence='PRIVATE-EVIDENCE-CANARY',source_page=1)
        task.assignee=self.person
        task.save()
        return doc,task

    def pending(self):
        person=FamilyPerson.objects.create(family=self.family,name='Invited adult')
        with patch('core.enrollment.enrollment_ready',return_value=True),patch('core.enrollment.send_mail',return_value=1) as send:
            inv=issue_invitation(owner=self.owner_member,email='invited@example.test',person=person)
        body=send.call_args.args[1]
        link=re.search(r'https?://\S+/join/#token=\S+',body)[0] if 'https://' in body else re.search(r'/join/#token=\S+',body)[0]
        token=parse_qs(urlsplit(link).fragment)['token'][0]
        code=re.search(r'Verification code: (\d{8})',body)[1]
        return inv,token,code

    def test_role_matrix_denies_all_owner_resources_even_to_staff(self):
        self.adult.is_staff=True
        self.adult.is_superuser=True
        self.adult.save()
        for path in ['/finance/','/goals/','/family/','/vault/','/tasks/','/tasks/new/','/members/',
                     '/api/v1/summary/','/api/v1/family/','/api/v1/audit/','/api/v1/invitations/']:
            with self.subTest(path=path):
                self.assertEqual(self.adult_client.get(path).status_code,403)
        self.assertRedirects(self.adult_client.get('/'),'/my/',fetch_redirect_response=False)
        self.assertEqual(self.adult_client.get('/my/').status_code,200)

    def test_assigned_task_does_not_share_source_or_evidence(self):
        doc,task=self.assigned()
        response=self.adult_client.get('/my/tasks/')
        self.assertContains(response,'Assigned review')
        self.assertContains(response,'Shared task notes')
        self.assertNotContains(response,'PRIVATE-DOCUMENT-CANARY')
        self.assertNotContains(response,'PRIVATE-EVIDENCE-CANARY')
        self.assertNotContains(response,str(doc.pk))
        self.assertEqual(self.adult_client.get(f'/vault/{doc.pk}/download/').status_code,404)
        self.assertEqual(self.adult_client.get(f'/tasks/{task.pk}/edit/').status_code,403)
        task.assignee=None
        task.save()
        self.assertNotContains(self.adult_client.get('/my/tasks/'),'Assigned review')
        self.assertEqual(self.adult_post(f'/my/tasks/{task.pk}/complete/',{'completed':'1','revision':1}).status_code,404)

    def test_explicit_grant_and_revocation_control_every_document_route(self):
        doc,_=self.assigned()
        grant=set_document_grant(owner=self.owner_member,document=doc,member=self.member,active=True)
        self.assertContains(self.adult_client.get('/my/documents/'),'PRIVATE-DOCUMENT-CANARY')
        self.assertContains(self.adult_client.get('/my/tasks/'),'PRIVATE-EVIDENCE-CANARY')
        for suffix in ['view','download']:
            self.assertEqual(self.adult_client.get(f'/vault/{doc.pk}/{suffix}/').status_code,200)
        self.post(f'/members/grants/{grant.pk}/revoke/')
        self.assertEqual(self.adult_client.get(f'/vault/{doc.pk}/view/').status_code,404)
        self.assertNotContains(self.adult_client.get('/my/documents/'),'PRIVATE-DOCUMENT-CANARY')
        self.assertNotContains(self.adult_client.get('/my/tasks/'),'PRIVATE-EVIDENCE-CANARY')

    def test_member_can_complete_only_current_assigned_occurrence(self):
        _,task=self.assigned()
        url=f'/my/tasks/{task.pk}/complete/'
        self.assertEqual(self.adult_client.get(url).status_code,405)
        self.assertEqual(self.adult_client.post(url,{'completed':'1','revision':1}).status_code,403)
        self.assertEqual(self.adult_post(url,{'completed':'1','revision':1}).status_code,302)
        self.assertEqual(self.adult_post(url,{'completed':'1','revision':1}).status_code,409)
        self.assertEqual(self.adult_post(url,{'completed':'0','revision':2}).status_code,400)
        task.refresh_from_db()
        self.assertTrue(task.completed)

    def test_disable_member_revokes_sessions_and_document_grants(self):
        doc,_=self.assigned()
        set_document_grant(owner=self.owner_member,document=doc,member=self.member,active=True)
        self.assertEqual(self.post(f'/members/{self.member.pk}/disable/').status_code,302)
        self.assertFalse(OwnerSession.objects.filter(user=self.adult).exists())
        self.assertFalse(DocumentReadGrant.objects.filter(membership=self.member,active=True).exists())
        self.assertRedirects(self.adult_client.get('/my/'),'/login/',fetch_redirect_response=False)
        self.assertEqual(self.post(f'/members/{self.owner_member.pk}/disable/').status_code,404)

    def test_disabled_gate_and_archived_label_reject_existing_sessions(self):
        with override_settings(FAMILY_ENROLLMENT_ENABLED=False):
            self.assertRedirects(self.adult_client.get('/my/'),'/login/',fetch_redirect_response=False)
            self.assertEqual(self.login(self.adult_client,'adult@example.test').status_code,400)
        self.login(self.adult_client,'adult@example.test')
        self.person.archived=True
        self.person.save()
        self.assertRedirects(self.adult_client.get('/my/'),'/login/',fetch_redirect_response=False)

    def test_invitation_tokens_and_codes_are_not_stored_plaintext(self):
        with override_settings(FAMILY_PUBLIC_ORIGIN='https://family.example.test'):
            inv,token,code=self.pending()
        self.assertNotEqual(inv.token_digest,token)
        self.assertNotIn(code,inv.verification_digest)
        with patch('core.enrollment.enrollment_ready',return_value=True):
            user=accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='New-long-synthetic-passphrase-392!')
            self.assertEqual(user.membership.role,Role.ADULT)
            self.assertEqual(user.membership.person_id,inv.person_id)
            with self.assertRaises(EnrollmentError):
                accept_invitation(token=token,code=code,email=inv.email,name='Replay',password='New-long-synthetic-passphrase-392!')

    def test_wrong_email_or_code_persists_failure_budget(self):
        inv,token,code=self.pending()
        with patch('core.enrollment.enrollment_ready',return_value=True):
            for _ in range(5):
                with self.assertRaises(EnrollmentError):
                    accept_invitation(token=token,code=code,email='wrong@example.test',name='Wrong',password='New-long-synthetic-passphrase-392!')
            with self.assertRaises(EnrollmentError):
                accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='New-long-synthetic-passphrase-392!')
        inv.refresh_from_db()
        self.assertEqual(inv.attempts,5)
        self.assertFalse(get_user_model().objects.filter(username=inv.email).exists())

    def test_expiry_revocation_and_get_never_accept_invitation(self):
        inv,token,code=self.pending()
        with patch('core.enrollment.enrollment_ready',return_value=True):
            with patch('core.enrollment_views.enrollment_ready',return_value=True):
                self.assertEqual(Client().get('/join/').status_code,200)
            inv.refresh_from_db()
            self.assertEqual(inv.status,'pending')
            Invitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
            with self.assertRaises(EnrollmentError):
                accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='New-long-synthetic-passphrase-392!')
            self.assertEqual(self.post(f'/members/invitations/{inv.pk}/revoke/').status_code,302)
            with self.assertRaises(EnrollmentError):
                accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='New-long-synthetic-passphrase-392!')

    def test_delivery_failure_revokes_pending_invitation(self):
        person=FamilyPerson.objects.create(family=self.family,name='Delivery test')
        with patch('core.enrollment.enrollment_ready',return_value=True),patch('core.enrollment.send_mail',side_effect=RuntimeError('private-provider-canary')):
            with self.assertRaises(EnrollmentError) as caught:
                issue_invitation(owner=self.owner_member,email='delivery@example.test',person=person)
        self.assertNotIn('private-provider-canary',str(caught.exception))
        self.assertEqual(Invitation.objects.get(email='delivery@example.test').status,'revoked')

    def test_existing_account_cannot_be_taken_over_by_invitation(self):
        with patch('core.enrollment.enrollment_ready',return_value=True),patch('core.enrollment.send_mail') as send:
            with self.assertRaises(EnrollmentError):
                issue_invitation(owner=self.owner_member,email=self.adult.email,person=self.person)
        send.assert_not_called()

    def test_production_delivery_gate_is_fail_closed(self):
        self.assertFalse(enrollment_ready())
        with override_settings(DEVELOPMENT=False,FAMILY_PUBLIC_ORIGIN='https://family.example.test',ALLOWED_HOSTS=['family.example.test'],EMAIL_HOST='smtp.example.test',DEFAULT_FROM_EMAIL='family@example.test',EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'):
            self.assertTrue(enrollment_ready())
            with override_settings(FAMILY_PUBLIC_ORIGIN='http://family.example.test'):
                self.assertFalse(enrollment_ready())
            with override_settings(FAMILY_PUBLIC_ORIGIN='https://unapproved.example.test'):
                self.assertFalse(enrollment_ready())

    def test_owner_management_and_password_change_preserve_session(self):
        self.assertContains(self.client.get('/members/'),'Enrollment is disabled')
        self.assertEqual(self.adult_client.get('/members/').status_code,403)
        token=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',self.adult_client.get('/password/change/').content.decode())[1]
        response=self.adult_client.post('/password/change/',{'old_password':'Synthetic-password-293!',
            'new_password1':'New-adult-passphrase-934!','new_password2':'New-adult-passphrase-934!','csrfmiddlewaretoken':token})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.adult_client.get('/my/').status_code,200)

    def test_children_dependents_and_unbound_adults_cannot_sign_in(self):
        for role in (Role.CHILD,Role.DEPENDENT):
            Membership.objects.filter(pk=self.member.pk).update(role=role)
            client=Client(enforce_csrf_checks=True)
            self.assertEqual(self.login(client,'adult@example.test').status_code,400)
        Membership.objects.filter(pk=self.member.pk).update(role=Role.ADULT,person=None)
        self.assertEqual(self.login(Client(enforce_csrf_checks=True),'adult@example.test').status_code,400)

    def test_forged_family_grant_and_adult_management_writes_are_denied(self):
        doc,_=self.assigned()
        forged=copy(self.member)
        forged.family_id=2
        with self.assertRaises(ValueError):
            set_document_grant(owner=self.owner_member,document=doc,member=forged,active=True)
        self.assertEqual(self.adult_post('/members/documents/share/',{'member':self.member.pk,'document':doc.pk}).status_code,403)
        self.assertFalse(DocumentReadGrant.objects.exists())

    def test_acceptance_rejects_weak_password_and_new_existing_identity(self):
        inv,token,code=self.pending()
        with patch('core.enrollment.enrollment_ready',return_value=True):
            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='123')
            self.assertFalse(get_user_model().objects.filter(username=inv.email).exists())
            existing=get_user_model().objects.create_user(username=inv.email,email=inv.email,password='Existing-secret-passphrase-493!')
            with self.assertRaises(EnrollmentError):
                accept_invitation(token=token,code=code,email=inv.email,name='Invited',password='New-long-synthetic-passphrase-392!')
            existing.refresh_from_db()
            self.assertTrue(existing.check_password('Existing-secret-passphrase-493!'))
            self.assertFalse(Membership.objects.filter(user=existing).exists())

    def test_acceptance_post_requires_csrf_and_never_honors_forged_role(self):
        inv,token,code=self.pending()
        with patch('core.enrollment.enrollment_ready',return_value=True),patch('core.enrollment_views.enrollment_ready',return_value=True):
            anonymous=Client(enforce_csrf_checks=True)
            data={'token':token,'code':code,'email':inv.email,'name':'Invited','password':'New-long-synthetic-passphrase-392!',
                  'confirm_password':'New-long-synthetic-passphrase-392!','role':'owner','family_id':'2'}
            self.assertEqual(anonymous.post('/join/',data).status_code,403)
            csrf=re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"',anonymous.get('/join/').content.decode())[1]
            self.assertEqual(anonymous.post('/join/',{**data,'csrfmiddlewaretoken':csrf}).status_code,302)
        accepted=get_user_model().objects.get(username=inv.email).membership
        self.assertEqual(accepted.role,Role.ADULT)
        self.assertEqual(accepted.family_id,self.family.pk)

    def test_resend_revokes_prior_link_and_recent_owner_session_is_required(self):
        inv,_,_=self.pending()
        with patch('core.enrollment.enrollment_ready',return_value=True),patch('core.enrollment.send_mail',return_value=1):
            newer=issue_invitation(owner=self.owner_member,email=inv.email,person=inv.person)
        inv.refresh_from_db()
        self.assertEqual(inv.status,'revoked')
        self.assertNotEqual(inv.token_digest,newer.token_digest)
        OwnerSession.objects.filter(user=self.owner).update(created_at=timezone.now()-timedelta(minutes=16))
        with patch('core.enrollment_views.issue_invitation') as issue:
            self.post('/members/invite/',{'email':'fresh@example.test','person':inv.person_id})
            issue.assert_not_called()
