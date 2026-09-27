"""Read-only Gmail transport. Provider bodies and tokens must never be logged."""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, quote, urlsplit
import requests
from django.conf import settings
from .storage import VaultError, cipher

SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API = 'https://gmail.googleapis.com/gmail/v1/users/me/'


class GmailError(VaultError):
    def __init__(self, status=0):
        self.status = status
        super().__init__('Gmail is unavailable. Reconnect if access was revoked.')


def configured():
    uri = urlsplit(settings.GMAIL_REDIRECT_URI)
    return bool(settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET and settings.VAULT_KEY
                and settings.VAULT_ROOT and settings.VAULT_CLAMD_HOST
                and uri.path == '/vault/gmail/callback/' and not uri.query and not uri.fragment
                and (uri.scheme == 'https' or (settings.DEVELOPMENT and uri.scheme == 'http' and uri.hostname in ('localhost', '127.0.0.1'))))


def authorization():
    if not configured():
        raise VaultError('Gmail connection is not configured by the operator.')
    cipher()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': settings.GMAIL_CLIENT_ID, 'redirect_uri': settings.GMAIL_REDIRECT_URI,
        'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent',
        'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
    })
    return url, {'state': state, 'verifier': verifier, 'created': time.time()}


def request_json(method, url, *, data=None, headers=None, params=None, limit=15_000_000):
    try:
        with requests.request(method, url, data=data, headers=headers, params=params,
                              timeout=(5, 30), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise GmailError(response.status_code)
            payload = bytearray()
            for chunk in response.iter_content(65536):
                payload.extend(chunk)
                if len(payload) > limit:
                    raise GmailError()
            import json
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise GmailError()
            return result
    except (requests.RequestException, ValueError):
        raise GmailError() from None


def exchange(code, verifier):
    tokens = request_json('POST', TOKEN_URL, data={
        'code': code, 'code_verifier': verifier, 'client_id': settings.GMAIL_CLIENT_ID,
        'client_secret': settings.GMAIL_CLIENT_SECRET, 'redirect_uri': settings.GMAIL_REDIRECT_URI,
        'grant_type': 'authorization_code',
    }, limit=65536)
    if not tokens.get('refresh_token') or not tokens.get('access_token') or SCOPE not in tokens.get('scope', '').split():
        raise GmailError()
    return {'refresh_token': tokens['refresh_token']}


class GmailClient:
    def __init__(self, credentials):
        tokens = request_json('POST', TOKEN_URL, data={
            'client_id': settings.GMAIL_CLIENT_ID, 'client_secret': settings.GMAIL_CLIENT_SECRET,
            'refresh_token': credentials['refresh_token'], 'grant_type': 'refresh_token',
        }, limit=65536)
        if not tokens.get('access_token'):
            raise GmailError()
        self.headers = {'Authorization': 'Bearer ' + tokens['access_token']}

    def get(self, resource, **params):
        return request_json('GET', API + resource, headers=self.headers, params=params)

    def message(self, message_id):
        return self.get('messages/' + quote(message_id, safe=''), format='full')

    def attachment(self, message_id, attachment_id):
        return self.get('messages/' + quote(message_id, safe='') + '/attachments/' + quote(attachment_id, safe=''))


def revoke(credentials):
    try:
        with requests.post('https://oauth2.googleapis.com/revoke', data={'token': credentials['refresh_token']},
                           timeout=(5, 15), allow_redirects=False) as response:
            return response.status_code in (200, 400)
    except requests.RequestException:
        return False
