"""Explicit family and resource permissions; labels alone confer no access."""
from django.conf import settings
from django.db.models import Q
from .models import Role


def eligible_member(member):
    if not member or not member.active or not member.user.is_active:
        return False
    if member.role == Role.OWNER:
        return True
    return bool(settings.FAMILY_ENROLLMENT_ENABLED and member.role == Role.ADULT and member.person_id
                and not member.person.archived and member.person.family_id == member.family_id)


def accessible_documents(member):
    from vault.models import Document
    records = Document.objects.filter(family_id=member.family_id)
    if member.role == Role.OWNER:
        return records
    if not eligible_member(member):
        return records.none()
    return records.filter(read_grants__membership=member,read_grants__active=True,archived=False,
        read_grants__membership__active=True,read_grants__membership__user__is_active=True,
        read_grants__membership__person__archived=False).distinct()


def assigned_tasks(member):
    from vault.models import DocumentTask
    if not eligible_member(member):
        return DocumentTask.objects.none()
    records = DocumentTask.objects.filter(family_id=member.family_id,archived=False)
    if member.role != Role.OWNER:
        records = records.filter(assignee_id=member.person_id,assignee__archived=False,
            assignee__membership__pk=member.pk,assignee__membership__active=True,
            assignee__membership__user__is_active=True)
    return records.filter(Q(source_document__isnull=True) | Q(source_document__family_id=member.family_id))
