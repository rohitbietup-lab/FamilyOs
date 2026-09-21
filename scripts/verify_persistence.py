"""Two-process persistence and backup/restore smoke test. Synthetic data only."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(args, env):
    return subprocess.run([sys.executable, 'manage.py', *args], cwd=ROOT, env=env, check=True, capture_output=True, text=True)


with tempfile.TemporaryDirectory(prefix='familyos-verify-') as directory:
    env = {**os.environ, 'FAMILYOS_ENV': 'development', 'FAMILYOS_DATA_DIR': directory, 'FAMILYOS_ALLOWED_HOSTS': 'testserver,localhost,127.0.0.1'}
    # Build the V1.4 schema first to exercise an actual upgrade, not just a fresh install.
    run(['migrate', 'auth', '--noinput'], env)
    run(['migrate', 'sessions', '--noinput'], env)
    run(['migrate', 'core', '0001', '--noinput'], env)
    run(['shell', '-c', '''
from unittest.mock import patch
from django.core.management import call_command
from django.test import Client
with patch('core.management.commands.bootstrap_owner.getpass', return_value='Synthetic-only-password-739!'):
    call_command('bootstrap_owner', email='owner@example.test', name='Test owner', family='Test family')
c = Client()
assert c.post('/login/', {'username':'owner@example.test','password':'Synthetic-only-password-739!'}).status_code == 302
assert c.post('/profile/', {'display_name':'Saved owner'}).status_code == 302
assert c.post('/api/v1/family/', {'name':'Persisted family','mission':'Across restarts','revision':1}).status_code == 200
from pathlib import Path
from django.conf import settings
Path(settings.DATABASES['default']['NAME']).with_suffix('.session-test').write_text(c.cookies['familyos_session'].value)
'''], env)
    run(['migrate', '--noinput'], env)
    run(['shell', '-c', '''
from django.test import Client
from django.conf import settings
from pathlib import Path
c = Client()
c.cookies['familyos_session'] = Path(settings.DATABASES['default']['NAME']).with_suffix('.session-test').read_text()
assert c.post('/finance/new/', {'name':'Test savings','kind':'asset','category':'cash','amount':'12345.67','valued_on':'2026-01-01','notes':'','revision':1}).status_code == 302
assert c.post('/goals/new/', {'title':'Test milestone','area':'education','target_date':'2040-12-31','progress':30,'status':'active','notes':'','revision':1}).status_code == 302
'''], env)
    run(['shell', '-c', '''
from django.test import Client
from django.conf import settings
from pathlib import Path
c = Client()
c.cookies['familyos_session'] = Path(settings.DATABASES['default']['NAME']).with_suffix('.session-test').read_text()
response = c.get('/api/v1/family/')
assert response.status_code == 200
assert response.json()['name'] == 'Persisted family'
assert response.json()['revision'] == 2
assert c.get('/api/v1/me/').json()['display_name'] == 'Saved owner'
assert c.get('/api/v1/audit/').json()['events'][0]['action'] == 'goal.created'
assert c.get('/api/v1/summary/').json()['finance']['assets_paise'] == '1234567'
assert c.get('/api/v1/summary/').json()['goals']['active'] == 1
'''], env)
    backup = Path(directory) / 'backup.sqlite3'
    run(['backup_database', str(backup)], env)
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT name FROM core_family').fetchone()[0] == 'Persisted family'
        assert db.execute('SELECT value_paise FROM core_financialrecord').fetchone()[0] == 1234567
        assert db.execute('SELECT progress FROM core_goal').fetchone()[0] == 30
    restored = Path(directory) / 'restored'
    restored.mkdir()
    with closing(sqlite3.connect(backup)) as source, closing(sqlite3.connect(restored / 'familyos.sqlite3')) as target:
        source.backup(target)
    run(['shell', '-c', "from core.models import Family, FinancialRecord, Goal; assert Family.objects.get().name == 'Persisted family'; assert FinancialRecord.objects.get().value_paise == 1234567; assert Goal.objects.get().progress == 30"], {**env, 'FAMILYOS_DATA_DIR': str(restored)})
    print('PASS: V1.4 upgrade, profile/family/session/finance/goal/audit persistence, backup and restore verified.')
