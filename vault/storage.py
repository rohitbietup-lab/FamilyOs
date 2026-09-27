"""Opaque encrypted objects, bounded parsing, and mandatory ClamAV scanning."""
import hashlib
import io
import json
import socket
import struct
import uuid
import warnings
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from PIL import Image
from pypdf import PdfReader


class VaultError(Exception):
    pass


class RejectedFile(VaultError):
    pass


def cipher():
    try:
        return Fernet(settings.VAULT_KEY.encode('ascii'))
    except (ValueError, UnicodeError):
        raise VaultError('Vault encryption is not configured.') from None


def seal(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def unseal(value):
    try:
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError):
        raise VaultError('Vault data could not be decrypted.') from None


def root():
    if not settings.VAULT_ROOT:
        raise VaultError('Private storage is not configured.')
    path = Path(settings.VAULT_ROOT).resolve()
    if path.is_relative_to(settings.BASE_DIR) or path.is_relative_to(Path(settings.STATIC_ROOT).resolve()):
        raise VaultError('Private storage must be outside the repository and static files.')
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise VaultError('Private storage is unavailable.') from None
    return path


def object_path(key):
    return root() / (str(uuid.UUID(str(key))) + '.enc')


def scan(data):
    """A dedicated, trusted ClamAV daemon; no shell command or bypass switch."""
    if not settings.VAULT_CLAMD_HOST:
        raise VaultError('Document scanning is not configured.')
    try:
        with socket.create_connection((settings.VAULT_CLAMD_HOST, settings.VAULT_CLAMD_PORT), timeout=10) as sock:
            sock.settimeout(30)
            sock.sendall(b'zINSTREAM\0')
            for offset in range(0, len(data), 65536):
                chunk = data[offset:offset+65536]
                sock.sendall(struct.pack('!I', len(chunk)) + chunk)
            sock.sendall(struct.pack('!I', 0))
            result = b''
            while b'\0' not in result and len(result) < 4096:
                part = sock.recv(1024)
                if not part:
                    break
                result += part
    except OSError:
        raise VaultError('Document scanner is unavailable. Try again later.') from None
    if result == b'stream: OK\0':
        return
    if b' FOUND\0' in result:
        raise RejectedFile('Document rejected by the malware scanner.')
    raise VaultError('Document scanner did not confirm the file is safe.')


def validate(data, filename):
    if not data or len(data) > settings.VAULT_MAX_BYTES:
        raise RejectedFile('Choose a nonempty document no larger than 10 MiB.')
    suffix = Path(filename).suffix.lower()
    scan(data)
    try:
        if suffix == '.pdf' and data.startswith(b'%PDF-'):
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted or not 0 < len(reader.pages) <= 500:
                raise ValueError()
            # Reject executable actions and embedded payloads rather than render them.
            for marker in (b'/JavaScript', b'/JS', b'/Launch', b'/EmbeddedFile', b'/OpenAction', b'/AA', b'/RichMedia'):
                if marker in data:
                    raise ValueError()
            return 'application/pdf'
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                allowed = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG'}
                if image.format != allowed.get(suffix) or image.width * image.height > 25_000_000:
                    raise ValueError()
                image.verify()
                return 'image/png' if suffix == '.png' else 'image/jpeg'
    except Exception:
        raise RejectedFile('Only valid, unencrypted PDF, PNG and JPEG documents are accepted.') from None


def write_object(key, data):
    path = object_path(key)
    encrypted = cipher().encrypt(data)
    created = False
    try:
        with path.open('xb') as stream:
            created = True
            stream.write(encrypted)
        path.chmod(0o600)
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise VaultError('Private storage is unavailable.') from None


def read_object(document):
    try:
        data = cipher().decrypt(object_path(document.storage_key).read_bytes())
    except (OSError, InvalidToken):
        raise VaultError('This stored document is unavailable. Restore it from a verified backup.') from None
    if len(data) != document.size or hashlib.sha256(data).hexdigest() != document.checksum:
        raise VaultError('Document integrity verification failed.')
    return data
