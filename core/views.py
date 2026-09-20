from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .forms import FamilyForm, OwnerLoginForm, ProfileForm
from .models import AuditEvent, Family, LoginThrottle, OwnerSession


def audit(request, action):
    AuditEvent.objects.create(actor=request.user, family=request.owner_membership.family, action=action)


def consume_login_attempt(request):
    """Reserve attempts BEFORE password hashing; shared across workers/restarts.

    A global budget bounds distributed guesses against this single-owner service.
    Peer addresses are read from REMOTE_ADDR, never untrusted forwarded headers.
    """
    now = timezone.now()
    keys = [('global', 50), ('peer:' + request.META.get('REMOTE_ADDR', 'unknown'), 10)]
    with transaction.atomic():
        buckets = []
        for raw, limit in keys:
            key = salted_hmac('familyos-login', raw, algorithm='sha256').hexdigest()
            bucket, _ = LoginThrottle.objects.get_or_create(key=key)
            if bucket.window_start <= now - timedelta(minutes=15):
                bucket.attempts = 0
                bucket.window_start = now
            buckets.append((bucket, limit))
        if any(bucket.attempts >= limit for bucket, limit in buckets):
            return False
        for bucket, _ in buckets:
            bucket.attempts += 1
            bucket.save()
    return True


@require_http_methods(['GET', 'POST'])
def sign_in(request):
    if request.owner_membership:
        return redirect('dashboard')
    if request.method == 'POST' and not consume_login_attempt(request):
        response = render(request, 'core/login.html', {'form': OwnerLoginForm(request), 'throttled': True}, status=429)
        response['Retry-After'] = '900'
        return response
    form = OwnerLoginForm(request, data=request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                login(request, form.get_user())
                # A fixed timestamp enforces absolute expiry even if the session is later saved.
                expiry = timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE)
                request.session.set_expiry(expiry)
                OwnerSession.objects.create(user=request.user, session_key=request.session.session_key, expires_at=expiry)
                AuditEvent.objects.create(actor=request.user, family=request.user.membership.family, action='auth.login')
            return redirect('dashboard')
        AuditEvent.objects.create(action='auth.login_failed')
    return render(request, 'core/login.html', {'form': form}, status=200 if request.method == 'GET' else 400)


@require_POST
def sign_out(request):
    with transaction.atomic():
        audit(request, 'auth.logout')
        OwnerSession.objects.filter(session_key=request.session.session_key).delete()
        logout(request)
    return redirect('login')


@require_GET
def dashboard(request):
    return render(request, 'core/dashboard.html', {
        'family': request.owner_membership.family,
        'events': AuditEvent.objects.filter(family=request.owner_membership.family)[:6],
    })


@require_http_methods(['GET', 'POST'])
def profile(request):
    form = ProfileForm(request.POST if request.method == 'POST' else None, initial={'display_name': request.user.first_name})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            request.user.first_name = form.cleaned_data['display_name']
            request.user.save(update_fields=['first_name'])
            audit(request, 'profile.updated')
        messages.success(request, 'Your profile has been saved.')
        return redirect('profile')
    return render(request, 'core/edit.html', {'form': form, 'title': 'Owner profile', 'description': 'Update your name. Your sign-in email is managed locally by the operator.'})


def save_family(request, form):
    with transaction.atomic():
        changed = Family.objects.filter(pk=request.owner_membership.family_id, revision=form.cleaned_data['revision']).update(
            name=form.cleaned_data['name'], mission=form.cleaned_data['mission'],
            revision=F('revision') + 1, updated_at=timezone.now(),
        )
        if changed:
            audit(request, 'family.updated')
        return bool(changed)


@require_http_methods(['GET', 'POST'])
def family_settings(request):
    form = FamilyForm(request.POST if request.method == 'POST' else None, instance=request.owner_membership.family)
    status = 200
    if request.method == 'POST' and form.is_valid():
        if save_family(request, form):
            messages.success(request, 'Family details saved.')
            return redirect('family')
        form.add_error(None, 'These details changed in another session. Reload before saving again.')
        status = 409
    return render(request, 'core/edit.html', {'form': form, 'title': 'Family settings', 'description': 'A shared home for your family’s plans. Changes are saved centrally.'}, status=status)


@require_GET
def sessions(request):
    now = timezone.now()
    active = OwnerSession.objects.filter(user=request.user, expires_at__gt=now, last_seen_at__gt=now - timedelta(seconds=settings.SESSION_IDLE_SECONDS)).order_by('-created_at')
    return render(request, 'core/sessions.html', {'sessions': active})


@require_POST
def revoke_session(request, session_id):
    with transaction.atomic():
        session = get_object_or_404(OwnerSession, pk=session_id, user=request.user)
        current = session.session_key == request.session.session_key
        Session.objects.filter(session_key=session.session_key).delete()
        session.delete()
        audit(request, 'session.revoked')
        if current:
            logout(request)
            return redirect('login')
    messages.success(request, 'Session signed out.')
    return redirect('sessions')


@require_POST
def revoke_all(request):
    with transaction.atomic():
        keys = OwnerSession.objects.filter(user=request.user).values_list('session_key', flat=True)
        Session.objects.filter(session_key__in=keys).delete()
        OwnerSession.objects.filter(user=request.user).delete()
        audit(request, 'session.revoked_all')
        logout(request)
    return redirect('login')


@require_GET
def api_me(request):
    return JsonResponse({'id': request.user.pk, 'email': request.user.email, 'display_name': request.user.first_name, 'role': request.owner_membership.role})


@require_http_methods(['GET', 'POST'])
def api_family(request):
    family = request.owner_membership.family
    if request.method == 'POST':
        # Form-encoded writes use the same validation and CSRF contract as the UI.
        form = FamilyForm(request.POST, instance=family)
        if not form.is_valid():
            return JsonResponse({'errors': form.errors.get_json_data()}, status=400)
        if not save_family(request, form):
            return JsonResponse({'error': 'Revision conflict. Reload before retrying.'}, status=409)
        family.refresh_from_db()
    return JsonResponse({'id': family.pk, 'name': family.name, 'mission': family.mission, 'revision': family.revision, 'enrollment_enabled': False})


@require_GET
def api_audit(request):
    events = AuditEvent.objects.filter(family=request.owner_membership.family).values('id', 'action', 'created_at')[:100]
    return JsonResponse({'events': list(events)})


@require_http_methods(['GET', 'POST'])
def invitations(request):
    return JsonResponse({'error': 'Family enrollment is disabled in V1.4.', 'enabled': False}, status=403)
