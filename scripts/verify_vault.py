"""Real process restart, migration and encrypted backup/restore using synthetic data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from cryptography.fernet import Fernet

REPO = Path(__file__).resolve().parent.parent


def run(env, *args, code=None):
    command = [sys.executable, 'manage.py', *args] if code is None else [sys.executable, '-c', code]
    subprocess.run(command, cwd=REPO, env=env, check=True, capture_output=True, text=True)


with tempfile.TemporaryDirectory(prefix='familyos-vault-') as temp:
    root = Path(temp)
    env = {**os.environ, 'FAMILYOS_ENV': 'development', 'DJANGO_SETTINGS_MODULE': 'config.settings',
           'FAMILYOS_DATA_DIR': str(root / 'live'), 'FAMILYOS_VAULT_ROOT': str(root / 'objects'),
           'FAMILYOS_VAULT_KEY': Fernet.generate_key().decode()}
    run(env, 'migrate', 'core', '0002', '--noinput')
    run(env, code="""
import django; django.setup()
from core.models import Family, FinancialRecord
Family.objects.create(name='Synthetic backup family')
FinancialRecord.objects.create(family_id=1,name='Synthetic asset',kind='asset',category='cash',value_paise=123,valued_on='2026-01-01')
""")
    run(env, 'migrate', '--noinput')
    run(env, code="""
import django; django.setup()
import io
from PIL import Image
from unittest.mock import patch
from vault.services import ingest
from vault.models import GmailConnection
from vault.storage import seal
image=io.BytesIO(); Image.new('RGB',(4,4),'white').save(image,format='PNG')
with patch('vault.storage.scan'):
    ingest(family_id=1,data=image.getvalue(),name='synthetic.png',category='other')
GmailConnection.objects.create(family_id=1,connected=True,credentials=seal({'refresh_token':'synthetic'}))
""")
    verify = """
import django; django.setup()
from core.models import FinancialRecord
from vault.models import Document
from vault.storage import read_object, unseal
assert FinancialRecord.objects.get().value_paise == 123
doc=Document.objects.get()
assert read_object(doc).startswith(b'\\x89PNG')
assert unseal(doc.details)['title']=='synthetic.png'
"""
    run(env, code=verify)
    backup = root / 'backup.enc'
    run(env, 'backup_vault', str(backup))
    assert b'SQLite format' not in backup.read_bytes()
    run(env, 'restore_vault', str(backup), str(root / 'restored'))
    restored_env = {**env, 'FAMILYOS_DATA_DIR': str(root / 'restored'), 'FAMILYOS_VAULT_ROOT': str(root / 'restored' / 'objects')}
    run(restored_env, code=verify+"\nfrom vault.models import GmailConnection\nassert not GmailConnection.objects.get().connected\nassert GmailConnection.objects.get().credentials == ''")
    wrong_env = {**env, 'FAMILYOS_VAULT_KEY': Fernet.generate_key().decode()}
    try:
        run(wrong_env, 'restore_vault', str(backup), str(root / 'wrong-key'))
        raise AssertionError('Wrong-key restore succeeded')
    except subprocess.CalledProcessError:
        pass
    assert not (root / 'wrong-key').exists()
    try:
        run(env, 'restore_vault', str(backup), str(root / 'restored'))
        raise AssertionError('Restore overwrote existing data')
    except subprocess.CalledProcessError:
        pass
print('Vault migration, restart persistence, encrypted backup/restore and failure checks passed.')
