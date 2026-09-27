import base64
import binascii
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .gmail import GmailClient, GmailError
from .models import GmailConnection
from .services import classify, ingest
from .storage import VaultError, RejectedFile, unseal, seal


class LeaseLost(VaultError):
    pass


def request_sync(family_id):
    now = timezone.now()
    return GmailConnection.objects.filter(family_id=family_id, connected=True, requested=False).filter(
        Q(last_attempt__isnull=True) | Q(last_attempt__lt=now-timedelta(minutes=5))
    ).update(requested=True, requested_at=now, status='queued')


def held(connection):
    return GmailConnection.objects.filter(pk=connection.pk, connected=True, generation=connection.generation, lease=connection.lease)


def renew(connection):
    if not held(connection).update(lease_until=timezone.now()+timedelta(minutes=5)):
        raise LeaseLost()


def parts(payload, depth=0):
    if depth > 20:
        return
    if payload.get('filename'):
        yield payload
    for child in payload.get('parts', []):
        yield from parts(child, depth+1)


def import_message(client, connection, message_id):
    renew(connection)
    try:
        message = client.message(message_id)
    except GmailError as exc:
        if exc.status == 404:  # Message removed after the listing.
            return 0, 0
        raise
    payload = message.get('payload', {})
    subject = next((h.get('value', '') for h in payload.get('headers', []) if h.get('name', '').lower() == 'subject'), '')
    count = skipped = 0
    for part in parts(payload):
        name = part['filename']
        category = classify(name + ' ' + subject)
        # Ingestion is intentionally conservative; manually upload unmatched documents.
        if not category:
            continue
        body = part.get('body', {})
        if body.get('size', 0) > settings.VAULT_MAX_BYTES:
            skipped += 1
            continue
        renew(connection)
        if body.get('attachmentId'):
            body = client.attachment(message_id, body['attachmentId'])
        encoded = body.get('data', '')
        if len(encoded) > (settings.VAULT_MAX_BYTES * 4 // 3) + 8:
            skipped += 1
            continue
        try:
            data = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        except (ValueError, binascii.Error):
            skipped += 1
            continue
        try:
            # Scan before the write lock; fence disconnect/reconnect at the final commit.
            _, created = ingest(family_id=connection.family_id, data=data, name=name, category=category,
                                source='gmail', source_id=message_id, guard=lambda: renew(connection))
            count += int(created)
        except RejectedFile:
            skipped += 1
    return count, skipped


def run_page():
    """Process one durable page; safe to run from multiple worker processes."""
    now = timezone.now()
    with transaction.atomic():
        connection = GmailConnection.objects.filter(connected=True, requested=True).filter(
            Q(lease_until__isnull=True) | Q(lease_until__lt=now)
        ).order_by('requested_at').first()
        if not connection:
            return False
        connection.lease = uuid.uuid4()
        connection.lease_until = now+timedelta(minutes=5)
        connection.last_attempt = now
        connection.status = 'syncing'
        connection.save(update_fields=['lease', 'lease_until', 'last_attempt', 'status'])
    try:
        client = GmailClient(unseal(connection.credentials))
        page_token = unseal(connection.page_token) if connection.page_token else ''
        params = {'maxResults': 10}
        if page_token:
            params['pageToken'] = page_token
        if connection.full_sync:
            if not connection.baseline_history:
                connection.baseline_history = client.get('profile')['historyId']
                held(connection).update(baseline_history=connection.baseline_history)
            result = client.get('messages', q='has:attachment -in:spam -in:trash', **params)
            ids = [item['id'] for item in result.get('messages', [])]
        else:
            try:
                result = client.get('history', startHistoryId=connection.history_id, historyTypes='messageAdded', **params)
            except GmailError as exc:
                if exc.status != 404:
                    raise
                held(connection).update(full_sync=True, page_token='', baseline_history='', status='queued', lease=None, lease_until=None)
                return True
            ids = list(dict.fromkeys(item['message']['id'] for event in result.get('history', []) for item in event.get('messagesAdded', [])))
        imported = skipped = 0
        for message_id in ids:
            new, rejected = import_message(client, connection, message_id)
            imported += new
            skipped += rejected
        with transaction.atomic():
            renew(connection)
            next_page = result.get('nextPageToken', '')
            values = {'page_token': seal(next_page) if next_page else '', 'lease': None, 'lease_until': None,
                      'imported': connection.imported+imported, 'skipped': connection.skipped+skipped, 'status': 'queued'}
            if not next_page:
                # Capture the full-sync watermark BEFORE listing so concurrent mail isn't lost.
                values.update(history_id=connection.baseline_history if connection.full_sync else result['historyId'],
                              full_sync=False, baseline_history='', requested=False, last_success=timezone.now(), status='ready')
            held(connection).update(**values)
    except (VaultError, KeyError, TypeError, ValueError):
        # Preserve checkpoint; replay is safe because content hashes are unique.
        held(connection).update(status='error', requested=False, lease=None, lease_until=None)
    return True
