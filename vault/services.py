import hashlib
import re
from pathlib import PurePosixPath
from django.db import transaction
from core.models import AuditEvent
from .models import Category, Document
from .storage import seal, unseal, validate, write_object, object_path


RULES = {
    Category.INSURANCE: r'\b(insurance|policy|premium)\b',
    Category.TAX: r'\b(tax|itr|form.?16|tds)\b',
    Category.PROPERTY: r'\b(property|deed|rent|lease|registration)\b',
    Category.BANKING: r'\b(bank|statement|investment|mutual fund|deposit|loan)\b',
    Category.EDUCATION: r'\b(school|education|tuition|report card|exam|admission)\b',
    Category.IDENTITY: r'\b(aadhaar|aadhar|passport|identity|pan card|licen[cs]e)\b',
    Category.MEDICAL: r'\b(medical|prescription|hospital|lab report|diagnostic|vaccin)\w*',
    Category.TRAVEL: r'\b(travel|ticket|itinerary|boarding|visa|booking)\b',
}


def classify(text):
    return next((category for category, pattern in RULES.items() if re.search(pattern, text, re.I)), None)


def filename(value):
    return ''.join(c for c in PurePosixPath(value.replace('\\', '/')).name if c.isprintable())[:160] or 'document.pdf'


def ingest(*, family_id, data, name, category, actor=None, source='manual', source_id='', values=None, guard=None):
    checksum = hashlib.sha256(data).hexdigest()
    existing = Document.objects.filter(family_id=family_id, checksum=checksum).first()
    if existing:
        return existing, False
    name = filename(name)
    mime = validate(data, name)
    values = values or {}
    doc = Document(family_id=family_id, category=category, checksum=checksum, size=len(data),
                   mime_type=mime, source=source, **{k: v for k, v in values.items() if k in ('person', 'expires_on', 'renew_on', 'starred')})
    doc.details = seal({'title': values.get('title', name), 'filename': name, 'notes': values.get('notes', ''), 'source_id': source_id})
    with transaction.atomic():
        if guard:
            guard()
        # SQLite IMMEDIATE serializes this final check and insertion across workers.
        existing = Document.objects.filter(family_id=family_id, checksum=checksum).first()
        if existing:
            return existing, False
        write_object(doc.storage_key, data)
        try:
            doc.save()
            AuditEvent.objects.create(family_id=family_id, actor=actor, action='vault.created')
        except Exception:
            object_path(doc.storage_key).unlink(missing_ok=True)
            raise
    return doc, True


def presentation(doc):
    details = unseal(doc.details)
    doc.title = details['title']
    doc.notes = details.get('notes', '')
    return doc
