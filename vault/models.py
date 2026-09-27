import uuid
from django.db import models
from django.db.models import Q
from django.utils import timezone
from core.models import FamilyRecord


class Category(models.TextChoices):
    INSURANCE = 'insurance', 'Insurance'
    TAX = 'tax', 'Tax'
    PROPERTY = 'property', 'Property'
    BANKING = 'banking', 'Banking / Investment'
    EDUCATION = 'education', 'Education'
    IDENTITY = 'identity', 'Identity'
    MEDICAL = 'medical', 'Medical'
    TRAVEL = 'travel', 'Travel'
    OTHER = 'other', 'Other'


class FamilyPerson(FamilyRecord):
    """Document association only; does not enroll a user or grant access."""
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ['name', 'id']


class Document(FamilyRecord):
    # Sensitive metadata is authenticated/encrypted with the object encryption key.
    details = models.TextField()
    category = models.CharField(max_length=16, choices=Category.choices)
    person = models.ForeignKey(FamilyPerson, null=True, blank=True, on_delete=models.PROTECT)
    expires_on = models.DateField(null=True, blank=True)
    renew_on = models.DateField(null=True, blank=True)
    starred = models.BooleanField(default=False)
    storage_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    checksum = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    mime_type = models.CharField(max_length=32)
    source = models.CharField(max_length=8, choices=[('manual', 'Manual'), ('gmail', 'Gmail')])

    class Meta:
        ordering = ['-starred', '-created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['family', 'checksum'], name='vault_unique_content'),
            models.CheckConstraint(condition=Q(category__in=Category.values), name='vault_valid_category'),
            models.CheckConstraint(condition=Q(source__in=['manual', 'gmail']), name='vault_valid_source'),
        ]


class GmailConnection(models.Model):
    family = models.OneToOneField('core.Family', primary_key=True, on_delete=models.PROTECT)
    credentials = models.TextField(blank=True)
    connected = models.BooleanField(default=False)
    generation = models.UUIDField(default=uuid.uuid4)
    history_id = models.CharField(max_length=40, blank=True)
    # Checkpoints advance only after a complete page has been persisted.
    full_sync = models.BooleanField(default=True)
    page_token = models.TextField(blank=True)
    baseline_history = models.CharField(max_length=40, blank=True)
    requested = models.BooleanField(default=False)
    requested_at = models.DateTimeField(null=True)
    last_attempt = models.DateTimeField(null=True)
    last_success = models.DateTimeField(null=True)
    status = models.CharField(max_length=24, default='disconnected')
    imported = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    lease = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(default=timezone.now)


class OAuthAttempt(models.Model):
    # One-time, session-bound authorization state. No authorization code is persisted.
    digest = models.CharField(max_length=64, primary_key=True)
    session_digest = models.CharField(max_length=64)
    pending = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
