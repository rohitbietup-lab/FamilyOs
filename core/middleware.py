from datetime import timedelta
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseForbidden, JsonResponse
from django.urls import resolve, Resolver404
from django.shortcuts import redirect
from django.utils import timezone
from .models import AuditEvent, Membership, OwnerSession, Role
from .access import eligible_member


class PrivateAccessMiddleware:
    """Deny by default: every application route except sign-in requires an owner."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public = request.path in ('/login/','/join/') or request.path.startswith('/static/')
        request.owner_membership = None
        request.family_membership = None
        if request.user.is_authenticated:
            member = Membership.objects.filter(user=request.user, active=True).select_related('family','user','person').first()
            session = OwnerSession.objects.filter(user=request.user, session_key=request.session.session_key).first()
            now = timezone.now()
            if eligible_member(member) and session and session.expires_at > now and session.last_seen_at > now - timedelta(seconds=settings.SESSION_IDLE_SECONDS):
                request.family_membership = member
                if member.role == Role.OWNER:
                    request.owner_membership = member
                OwnerSession.objects.filter(pk=session.pk).update(last_seen_at=now)
            else:
                if session:
                    AuditEvent.objects.create(actor=request.user, family=member.family if member else None, action='session.invalidated')
                    session.delete()
                logout(request)
        if not public and request.family_membership is None:
            response = JsonResponse({'error': 'Authentication required.'}, status=401) if request.path.startswith('/api/') else redirect('login')
        elif not public and request.owner_membership is None:
            try:
                route = resolve(request.path_info).url_name
            except Resolver404:
                route = None
            if route == 'dashboard':
                response = redirect('member-home')
            elif route in {'member-home','member-tasks','member-task-complete','member-documents',
                           'vault-view','vault-download','profile','sessions','revoke-session','revoke-all','logout','password-change'}:
                response = self.get_response(request)
            else:
                response = HttpResponseForbidden('This page is not shared with your account.')
        else:
            response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        if 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; form-action 'self' https://accounts.google.com; base-uri 'none'; frame-ancestors 'none'"
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
