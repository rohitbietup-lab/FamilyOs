import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Family(models.Model):
    # V1.4 is a single-family, owner-only installation.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=100)
    mission = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name='single_family')]


class Role(models.TextChoices):
    OWNER = 'owner', 'Owner'
    ADULT = 'adult', 'Adult / Parent'
    CHILD = 'child', 'Child'
    DEPENDENT = 'dependent', 'Dependent'


class Membership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    family = models.ForeignKey(Family, on_delete=models.PROTECT)
    role = models.CharField(max_length=16, choices=Role.choices)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['family'], condition=Q(role='owner'), name='one_owner_per_family'),
            models.CheckConstraint(condition=Q(role__in=Role.values), name='valid_member_role'),
        ]


class AuditEvent(models.Model):
    family = models.ForeignKey(Family, null=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=50)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    @property
    def label(self):
        return {
            'owner.bootstrapped': 'Owner account created',
            'auth.login': 'Signed in', 'auth.logout': 'Signed out',
            'profile.updated': 'Owner profile updated', 'family.updated': 'Family details updated',
            'session.revoked': 'Session signed out', 'session.revoked_all': 'All sessions signed out',
            'session.invalidated': 'Session ended',
        }.get(self.action, 'Account activity')

    class Meta:
        ordering = ['-created_at', '-id']


class OwnerSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # Server-side only; the UI uses the unrelated UUID, never a session credential.
    session_key = models.CharField(max_length=40, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    attempts = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField(default=timezone.now)


class Invitation(models.Model):
    """Schema reserved for Stage 5; no issuance, token, or acceptance path in V1.4."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(Family, on_delete=models.PROTECT)
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=Role.choices)
    status = models.CharField(max_length=16, default='disabled', editable=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(status='disabled'), name='invitations_disabled')]
