from datetime import timedelta
from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from .models import AuditEvent, Membership, OwnerSession, Role


class PrivateAccessMiddleware:
    """Deny by default: every application route except sign-in requires an owner."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public = request.path == '/login/' or request.path.startswith('/static/')
        request.owner_membership = None
        if request.user.is_authenticated:
            member = Membership.objects.filter(user=request.user, active=True, role=Role.OWNER).select_related('family').first()
            session = OwnerSession.objects.filter(user=request.user, session_key=request.session.session_key).first()
            now = timezone.now()
            if member and session and session.expires_at > now and session.last_seen_at > now - timedelta(seconds=settings.SESSION_IDLE_SECONDS):
                request.owner_membership = member
                OwnerSession.objects.filter(pk=session.pk).update(last_seen_at=now)
            else:
                if session:
                    AuditEvent.objects.create(actor=request.user, family=member.family if member else None, action='session.invalidated')
                    session.delete()
                logout(request)
        if not public and request.owner_membership is None:
            response = JsonResponse({'error': 'Authentication required.'}, status=401) if request.path.startswith('/api/') else redirect('login')
        else:
            response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
