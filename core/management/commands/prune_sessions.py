from datetime import timedelta
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import LoginThrottle, OwnerSession


class Command(BaseCommand):
    help = 'Remove expired session records and old throttle buckets; retain audit history.'

    def handle(self, *args, **options):
        now = timezone.now()
        Session.objects.filter(expire_date__lte=now).delete()
        expired = OwnerSession.objects.filter(last_seen_at__lte=now-timedelta(seconds=settings.SESSION_IDLE_SECONDS))
        Session.objects.filter(session_key__in=expired.values('session_key')).delete()
        expired.delete()
        OwnerSession.objects.filter(expires_at__lte=now).delete()
        OwnerSession.objects.exclude(session_key__in=Session.objects.values('session_key')).delete()
        LoginThrottle.objects.filter(window_start__lt=now-timedelta(days=1)).delete()
        self.stdout.write('Expired sessions and throttle buckets removed.')
