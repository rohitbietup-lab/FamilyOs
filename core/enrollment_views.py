from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .enrollment import EnrollmentError, enrollment_ready, issue_invitation, accept_invitation
from .models import AuditEvent, Invitation, Membership, OwnerSession, Role
from .views import consume_login_attempt
from .access import eligible_member
from vault.models import FamilyPerson, Document, DocumentReadGrant
from vault.grants import set_document_grant
from vault.storage import unseal, VaultError


class InviteForm(forms.Form):
    email=forms.EmailField(max_length=150)
    person=forms.ModelChoiceField(queryset=FamilyPerson.objects.none(),label='Family member label')

    def __init__(self,*args,family_id,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['person'].queryset=FamilyPerson.objects.filter(family_id=family_id,archived=False,membership__isnull=True)
        self.fields['person'].label_from_instance=lambda p:p.name


class AcceptForm(forms.Form):
    token=forms.CharField(max_length=128,widget=forms.HiddenInput)
    email=forms.EmailField(max_length=150)
    code=forms.RegexField(r'^\d{8}$',label='Eight-digit code from your invitation email',widget=forms.TextInput(attrs={'autocomplete':'one-time-code'}))
    name=forms.CharField(max_length=150,label='Your name')
    password=forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    confirm_password=forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))

    def clean(self):
        values=super().clean()
        if values.get('password')!=values.get('confirm_password'):
            self.add_error('confirm_password','Passwords must match.')
        return values


class DocumentChoice(forms.ModelChoiceField):
    def label_from_instance(self,doc):
        try:
            return unseal(doc.details)['title']
        except VaultError:
            return 'Document temporarily unavailable'


class GrantForm(forms.Form):
    member=forms.ModelChoiceField(queryset=Membership.objects.none(),label='Adult member')
    document=DocumentChoice(queryset=Document.objects.none())

    def __init__(self,*args,family_id,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['member'].queryset=Membership.objects.filter(family_id=family_id,role=Role.ADULT,active=True,
            user__is_active=True,person__family_id=family_id,person__archived=False).select_related('user')
        self.fields['member'].label_from_instance=lambda m:m.user.email
        self.fields['document'].queryset=Document.objects.filter(family_id=family_id,archived=False)


@require_GET
def members(request):
    family_id=request.owner_membership.family_id
    adults=list(Membership.objects.filter(family_id=family_id,role=Role.ADULT).select_related('user','person'))
    grants=DocumentReadGrant.objects.filter(document__family_id=family_id,membership__family_id=family_id,active=True).select_related('document','membership__user')
    for grant in grants:
        try:
            grant.title=unseal(grant.document.details)['title']
        except VaultError:
            grant.title='Document temporarily unavailable'
    return render(request,'core/members.html',{'ready':enrollment_ready(),
        'invite_form':InviteForm(family_id=family_id),'grant_form':GrantForm(family_id=family_id),
        'members':adults, 'can_share':any(eligible_member(member) for member in adults),
        'invitations':Invitation.objects.filter(family_id=family_id).exclude(status='disabled').order_by('-created_at')[:30],
        'grants':grants})


@require_POST
def invite(request):
    session=OwnerSession.objects.get(user=request.user,session_key=request.session.session_key)
    if session.created_at < timezone.now()-timedelta(minutes=15):
        messages.error(request,'Sign out and sign back in before sending an invitation.')
        return redirect('members')
    form=InviteForm(request.POST,family_id=request.owner_membership.family_id)
    if not form.is_valid():
        return HttpResponseBadRequest('Choose a valid email and active unlinked family label.')
    try:
        issue_invitation(owner=request.owner_membership,**form.cleaned_data)
    except EnrollmentError as exc:
        messages.error(request,str(exc))
    else:
        messages.success(request,'Invitation sent to the specified email address.')
    return redirect('members')


@require_POST
def revoke_invite(request,invitation_id):
    inv=get_object_or_404(Invitation,pk=invitation_id,family_id=request.owner_membership.family_id,status='pending')
    Invitation.objects.filter(pk=inv.pk,status='pending').update(status='revoked',verification_digest='')
    AuditEvent.objects.create(family=inv.family,actor=request.user,action='invitation.revoked')
    return redirect('members')


@sensitive_post_parameters('token','code','password','confirm_password')
@require_http_methods(['GET','POST'])
def join(request):
    if not enrollment_ready():
        raise Http404()
    if request.user.is_authenticated:
        return HttpResponseBadRequest('Sign out before accepting a different account invitation.')
    form=AcceptForm(request.POST if request.method=='POST' else None)
    status=200
    if request.method=='POST':
        status=400
        if not consume_login_attempt(request):
            return HttpResponseBadRequest('Please wait before trying again.')
        if form.is_valid():
            try:
                values=form.cleaned_data.copy()
                values.pop('confirm_password')
                accept_invitation(**values)
            except (EnrollmentError,forms.ValidationError) as exc:
                form.add_error(None,str(exc) if isinstance(exc,EnrollmentError) else 'Choose a stronger password.')
            else:
                messages.success(request,'Your adult account is ready. Sign in with your email and chosen password.')
                return redirect('login')
    response=render(request,'core/join.html',{'form':form},status=status)
    response['Referrer-Policy']='no-referrer'
    return response


@require_POST
def disable_member(request,member_id):
    member=get_object_or_404(Membership,pk=member_id,family_id=request.owner_membership.family_id,role=Role.ADULT)
    with transaction.atomic():
        Membership.objects.filter(pk=member.pk).update(active=False)
        keys=OwnerSession.objects.filter(user=member.user).values_list('session_key',flat=True)
        Session.objects.filter(session_key__in=keys).delete()
        OwnerSession.objects.filter(user=member.user).delete()
        DocumentReadGrant.objects.filter(membership=member).update(active=False)
        AuditEvent.objects.create(family=member.family,actor=request.user,action='member.disabled')
    return redirect('members')


@require_POST
def share_document(request):
    form=GrantForm(request.POST,family_id=request.owner_membership.family_id)
    if not form.is_valid():
        return HttpResponseBadRequest('Choose an active adult and document from this family.')
    try:
        set_document_grant(owner=request.owner_membership,document=form.cleaned_data['document'],member=form.cleaned_data['member'],active=True)
    except (ValueError,PermissionError):
        return HttpResponseBadRequest('The document cannot be shared with this member.')
    return redirect('members')


@require_POST
def revoke_grant(request,grant_id):
    grant=get_object_or_404(DocumentReadGrant,pk=grant_id,document__family_id=request.owner_membership.family_id,membership__family_id=request.owner_membership.family_id)
    DocumentReadGrant.objects.filter(pk=grant.pk).update(active=False)
    AuditEvent.objects.create(family_id=request.owner_membership.family_id,actor=request.user,action='document.revoked')
    return redirect('members')


@sensitive_post_parameters('old_password','new_password1','new_password2')
@require_http_methods(['GET','POST'])
def password_change(request):
    form=PasswordChangeForm(request.user,request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            old_key=request.session.session_key
            form.save()
            update_session_auth_hash(request,request.user)
            others=OwnerSession.objects.filter(user=request.user).exclude(session_key=old_key)
            Session.objects.filter(session_key__in=others.values_list('session_key',flat=True)).delete()
            others.delete()
            OwnerSession.objects.filter(user=request.user,session_key=old_key).update(session_key=request.session.session_key)
            AuditEvent.objects.create(family=request.family_membership.family,actor=request.user,action='auth.password_changed')
        return redirect('profile')
    return render(request,'core/edit.html',{'form':form,'title':'Change your password','description':'Other sessions are signed out after a password change.'})
