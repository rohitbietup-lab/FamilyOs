from django.db import transaction
from core.access import eligible_member
from core.models import AuditEvent, Role
from .models import DocumentReadGrant


def set_document_grant(*, owner, document, member, active):
    if not eligible_member(owner) or owner.role != Role.OWNER or owner.family_id != document.family_id:
        raise PermissionError('Owner access required.')
    if member.family_id != owner.family_id or member.role != Role.ADULT or not eligible_member(member) or document.archived:
        raise ValueError('Choose an active adult and active same-family document.')
    with transaction.atomic():
        grant, _ = DocumentReadGrant.objects.update_or_create(document=document,membership=member,defaults={'active':active})
        AuditEvent.objects.create(family_id=owner.family_id,actor=owner.user,
            action='document.granted' if active else 'document.revoked')
    return grant
