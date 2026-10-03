"""Load a Google Web client download without exposing credential contents."""
import json
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def load_web_client(path, redirect_uri=''):
    try:
        with Path(path).open(encoding='utf-8-sig') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError
        document = json.loads(raw)
        web = document.get('web') if isinstance(document, dict) else None
        if not isinstance(web, dict):
            raise ImproperlyConfigured('Gmail requires a Web application OAuth client JSON, not a Desktop client.')
        client_id, secret = web.get('client_id'), web.get('client_secret')
        uris = web.get('redirect_uris')
        if not all(isinstance(value, str) and value.strip() for value in (client_id, secret)):
            raise ValueError
        if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) and uri for uri in uris):
            raise ValueError
        if not redirect_uri and len(uris) == 1:
            redirect_uri = uris[0]
        if not redirect_uri or redirect_uri not in uris:
            raise ImproperlyConfigured('Set FAMILYOS_GMAIL_REDIRECT_URI to an exact redirect URI registered in the Web client JSON.')
        return client_id, secret, redirect_uri
    except (OSError, ValueError, TypeError):
        raise ImproperlyConfigured('Cannot load Gmail Web client JSON. Check its path, format and required fields.') from None
