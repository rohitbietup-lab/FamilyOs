import io
import hashlib
import secrets
import time
import uuid
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from core.central import scoped
from core.models import AuditEvent
from core.record_forms import RevisionForm
from . import gmail
from .forms import DocumentForm, UploadForm, PersonForm
from .models import Category, Document, FamilyPerson, GmailConnection, OAuthAttempt
from .services import ingest, presentation
from .storage import VaultError, read_object, unseal, seal
from .sync import request_sync


def audit(request, action):
    AuditEvent.objects.create(family_id=request.owner_membership.family_id, actor=request.user, action=action)


@require_GET
def index(request):
    documents = scoped(request, Document).select_related('person').filter(archived=request.GET.get('archived') == '1')
    category = request.GET.get('category', '')
    if category in Category.values:
        documents = documents.filter(category=category)
    if request.GET.get('starred') == '1':
        documents = documents.filter(starred=True)
    if request.GET.get('expiring') == '1':
        from datetime import timedelta
        from django.db.models import Q
        until = timezone.localdate()+timedelta(days=30)
        documents = documents.filter(Q(expires_on__lte=until) | Q(renew_on__lte=until))
    page = Paginator(documents, 20).get_page(request.GET.get('page'))
    unavailable = False
    for document in page:
        try:
            presentation(document)
        except VaultError:
            document.title = 'Document temporarily unavailable'
            unavailable = True
    return render(request, 'vault/index.html', {'page': page, 'categories': Category.choices, 'category': category,
        'connection': GmailConnection.objects.filter(pk=request.owner_membership.family_id).first(),
        'gmail_configured': gmail.configured(), 'unavailable': unavailable,
        'filters': request.GET.urlencode(), 'archived': request.GET.get('archived') == '1'})


@require_http_methods(['GET', 'POST'])
def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None, family_id=request.owner_membership.family_id)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            file = form.cleaned_data['file']
            from django.conf import settings
            try:
                if file.size > settings.VAULT_MAX_BYTES:
                    raise VaultError('Choose a document no larger than 10 MiB.')
                _, created = ingest(family_id=request.owner_membership.family_id, actor=request.user,
                                    data=file.read(settings.VAULT_MAX_BYTES+1), name=file.name,
                                    category=form.cleaned_data['category'], values=form.cleaned_data)
                messages.success(request, 'Document saved.' if created else 'This document is already in your Vault, including its archive.')
                return redirect('vault')
            except VaultError as exc:
                form.add_error(None, str(exc))
    return render(request, 'vault/form.html', {'form': form, 'title': 'Add a document', 'upload': True}, status=status)


@require_http_methods(['GET', 'POST'])
def edit(request, document_id):
    document = get_object_or_404(scoped(request, Document), pk=document_id, archived=False)
    try:
        details = unseal(document.details)
    except VaultError:
        return HttpResponse('Document metadata is unavailable. Contact the operator.', status=503)
    initial = {key: getattr(document, key) for key in ('category', 'person', 'expires_on', 'renew_on', 'starred', 'revision')}
    initial.update(title=details['title'], notes=details.get('notes', ''))
    form = DocumentForm(request.POST or None, initial=initial, family_id=request.owner_membership.family_id)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            values = form.cleaned_data.copy()
            revision = values.pop('revision')
            details.update(title=values.pop('title'), notes=values.pop('notes'))
            with transaction.atomic():
                changed = scoped(request, Document).filter(pk=document.pk, revision=revision, archived=False).update(
                    **values, details=seal(details), revision=F('revision')+1, updated_at=timezone.now())
                if changed:
                    audit(request, 'vault.updated')
            if changed:
                messages.success(request, 'Document details saved.')
                return redirect('vault')
            form.add_error(None, 'This document changed in another session. Reload before saving.')
            status = 409
    return render(request, 'vault/form.html', {'form': form, 'title': 'Edit document details'}, status=status)


@require_GET
def download(request, document_id, inline=False):
    document = get_object_or_404(scoped(request, Document), pk=document_id)
    try:
        data = read_object(document)
        details = unseal(document.details)
    except VaultError as exc:
        return HttpResponse(str(exc), status=503, content_type='text/plain')
    audit(request, 'vault.viewed' if inline else 'vault.downloaded')
    response = FileResponse(io.BytesIO(data), content_type=document.mime_type, as_attachment=not inline, filename=details['filename'])
    response['Content-Security-Policy'] = "sandbox; default-src 'none'; frame-ancestors 'none'"
    return response


@require_http_methods(['GET', 'POST'])
def archive(request, document_id):
    document = get_object_or_404(scoped(request, Document), pk=document_id)
    form = RevisionForm(request.POST or None, initial={'revision': document.revision})
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            with transaction.atomic():
                changed = scoped(request, Document).filter(pk=document.pk, revision=form.cleaned_data['revision']).update(
                    archived=not document.archived, revision=F('revision')+1, updated_at=timezone.now())
                if changed:
                    audit(request, 'vault.restored' if document.archived else 'vault.archived')
            if changed:
                return redirect('vault')
            form.add_error(None, 'This document changed. Reload before trying again.')
            status = 409
    return render(request, 'vault/form.html', {'form': form, 'title': 'Restore document' if document.archived else 'Archive document'}, status=status)


@require_http_methods(['GET', 'POST'])
def person(request):
    form = PersonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            FamilyPerson.objects.create(family_id=request.owner_membership.family_id, name=form.cleaned_data['name'])
            audit(request, 'vault.person_added')
        messages.success(request, 'Family member added for document association. No account or access was created.')
        return redirect('vault-upload')
    return render(request, 'vault/form.html', {'form': form, 'title': 'Add a family member label'}, status=400 if request.method == 'POST' else 200)


@require_POST
def connect(request):
    try:
        url, pending = gmail.authorization()
    except VaultError as exc:
        messages.error(request, str(exc))
        return redirect('vault')
    connection = GmailConnection.objects.filter(pk=request.owner_membership.family_id).first()
    pending['generation'] = str(connection.generation) if connection else None
    session_digest = hashlib.sha256(request.session.session_key.encode()).hexdigest()
    from datetime import timedelta
    with transaction.atomic():
        OAuthAttempt.objects.filter(session_digest=session_digest).delete()
        OAuthAttempt.objects.filter(created_at__lt=timezone.now()-timedelta(minutes=10)).delete()
        OAuthAttempt.objects.create(digest=hashlib.sha256(pending['state'].encode()).hexdigest(),
                                   session_digest=session_digest, pending=seal(pending))
    request.session['gmail_oauth'] = pending['state']
    return redirect(url)


@require_GET
def callback(request):
    state = request.session.pop('gmail_oauth', '')
    with transaction.atomic():
        attempt = OAuthAttempt.objects.filter(digest=hashlib.sha256(state.encode()).hexdigest(),
            session_digest=hashlib.sha256(request.session.session_key.encode()).hexdigest()).first()
        pending = None
        if attempt:
            attempt.delete()
            try:
                pending = unseal(attempt.pending)
            except VaultError:
                pass
    if (not pending or time.time()-pending['created'] > 600
            or not secrets.compare_digest(pending['state'], request.GET.get('state', ''))):
        return HttpResponse('Invalid or expired Gmail connection request.', status=400)
    if request.GET.get('error') or not request.GET.get('code'):
        messages.error(request, 'Gmail access was not granted.')
        return redirect('vault')
    try:
        credentials = gmail.exchange(request.GET['code'], pending['verifier'])
        with transaction.atomic():
            current = GmailConnection.objects.filter(pk=request.owner_membership.family_id).first()
            generation = str(current.generation) if current else None
            if generation != pending['generation']:
                raise VaultError('Gmail connection changed. Start again.')
            GmailConnection.objects.update_or_create(family_id=request.owner_membership.family_id, defaults={
                'credentials': seal(credentials), 'connected': True, 'generation': uuid.uuid4(), 'history_id': '',
                'full_sync': True, 'page_token': '', 'baseline_history': '', 'requested': True,
                'requested_at': timezone.now(), 'last_attempt': None, 'last_success': None, 'status': 'queued',
                'lease': None, 'lease_until': None, 'imported': 0, 'skipped': 0,
            })
            audit(request, 'vault.gmail_connected')
        messages.success(request, 'Gmail connected with read-only access. Document import is queued.')
    except VaultError:
        messages.error(request, 'Gmail could not be connected. Try connecting again.')
    return redirect('vault')


@require_POST
def disconnect(request):
    with transaction.atomic():
        connection = GmailConnection.objects.filter(pk=request.owner_membership.family_id).first()
        encrypted = connection.credentials if connection else ''
        if connection:
            connection.credentials = ''
            connection.connected = False
            connection.requested = False
            connection.generation = uuid.uuid4()
            connection.page_token = ''
            connection.status = 'disconnected'
            connection.save()
            audit(request, 'vault.gmail_disconnected')
    request.session.pop('gmail_oauth', None)
    OAuthAttempt.objects.filter(session_digest=hashlib.sha256(request.session.session_key.encode()).hexdigest()).delete()
    revoked = True
    if encrypted:
        try:
            revoked = gmail.revoke(unseal(encrypted))
        except VaultError:
            revoked = False
    messages.success(request, 'Gmail disconnected. Stored documents remain available.')
    if not revoked:
        messages.warning(request, 'Google revocation could not be confirmed. Remove FamilyOS access in your Google Account connections.')
    return redirect('vault')


@require_POST
def refresh(request):
    queued = bool(request_sync(request.owner_membership.family_id))
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'queued': queued})
    messages.info(request, 'Refresh queued.' if queued else 'Refresh is already queued, was recently checked, or Gmail is disconnected.')
    return redirect('vault')
