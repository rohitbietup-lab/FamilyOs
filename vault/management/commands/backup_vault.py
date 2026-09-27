import io
import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from vault.models import Document
from vault.storage import cipher, object_path, read_object, VaultError


class Command(BaseCommand):
    help = 'Create an encrypted database + Vault object backup outside the repository. Keep the Vault key separately.'

    def add_arguments(self, parser):
        parser.add_argument('destination')

    def handle(self, *args, **options):
        destination = Path(options['destination']).resolve()
        if destination.is_relative_to(settings.BASE_DIR):
            raise CommandError('Choose a backup destination outside the repository.')
        try:
            # Object contents are immutable, so the SQLite snapshot defines the backup set.
            with tempfile.TemporaryDirectory() as temp:
                snapshot = Path(temp) / 'familyos.sqlite3'
                with closing(sqlite3.connect(settings.DATABASES['default']['NAME'])) as src, closing(sqlite3.connect(snapshot)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise CommandError('Database integrity check failed.')
                    rows = dst.execute('SELECT storage_key, checksum, size FROM vault_document').fetchall()
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as bundle:
                    bundle.write(snapshot, 'familyos.sqlite3')
                    for key, checksum, size in rows:
                        doc = Document(storage_key=key, checksum=checksum, size=size)
                        read_object(doc)  # Authenticate every referenced object before accepting backup.
                        bundle.write(object_path(key), 'objects/' + object_path(key).name)
                    bundle.writestr('manifest.json', json.dumps({'format': 1, 'objects': len(rows)}))
                encrypted = cipher().encrypt(archive.getvalue())
                with destination.open('xb') as output:
                    output.write(encrypted)
                destination.chmod(0o600)
        except (OSError, sqlite3.Error, VaultError) as exc:
            raise CommandError('Vault backup failed. Check storage, key and destination.') from exc
        self.stdout.write(self.style.SUCCESS('Encrypted database and Vault backup verified and saved.'))
