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
            'finance.created': 'Financial record added', 'finance.updated': 'Financial record updated',
            'finance.archived': 'Financial record archived', 'finance.restored': 'Financial record restored',
            'goal.created': 'Goal added', 'goal.updated': 'Goal updated',
            'goal.archived': 'Goal archived', 'goal.restored': 'Goal restored',
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


class FamilyRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(Family, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    archived = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FinancialRecord(FamilyRecord):
    class Kind(models.TextChoices):
        ASSET = 'asset', 'Asset'
        LIABILITY = 'liability', 'Liability'

    class Category(models.TextChoices):
        CASH = 'cash', 'Cash / bank balance'
        INVESTMENT = 'investment', 'Investment'
        PROPERTY = 'property', 'Property'
        RETIREMENT = 'retirement', 'Retirement savings'
        LOAN = 'loan', 'Loan'
        MORTGAGE = 'mortgage', 'Home loan'
        CREDIT = 'credit', 'Credit card balance'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    category = models.CharField(max_length=16, choices=Category.choices)
    # Integer minor units keep money exact, including on SQLite. INR only in Stage 2.
    value_paise = models.PositiveBigIntegerField()
    valued_on = models.DateField()
    notes = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ['name', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(value_paise__gte=0, value_paise__lte=999999999999999), name='valid_finance_value'),
            models.CheckConstraint(condition=(
                Q(kind='asset', category__in=['cash', 'investment', 'property', 'retirement', 'other']) |
                Q(kind='liability', category__in=['loan', 'mortgage', 'credit', 'other'])
            ), name='finance_category_matches_kind'),
        ]


class Goal(FamilyRecord):
    class Area(models.TextChoices):
        FINANCE = 'finance', 'Finance'
        EDUCATION = 'education', 'Education'
        HEALTH = 'health', 'Health'
        LIFESTYLE = 'lifestyle', 'Lifestyle'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused'
        COMPLETED = 'completed', 'Completed'

    title = models.CharField(max_length=160)
    area = models.CharField(max_length=16, choices=Area.choices)
    target_date = models.DateField()
    progress = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    notes = models.CharField(max_length=1000, blank=True)

    @property
    def overdue(self):
        return self.status == self.Status.ACTIVE and self.target_date < timezone.localdate()

    class Meta:
        ordering = ['target_date', 'id']
        constraints = [
            models.CheckConstraint(condition=Q(progress__gte=0, progress__lte=100), name='valid_goal_progress'),
            models.CheckConstraint(condition=Q(area__in=['finance', 'education', 'health', 'lifestyle', 'other']), name='valid_goal_area'),
            models.CheckConstraint(condition=(
                Q(status='completed', progress=100) |
                Q(status__in=['active', 'paused'], progress__lt=100)
            ), name='goal_status_matches_progress'),
        ]
