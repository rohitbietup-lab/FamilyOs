import hashlib
import io
import json
import sqlite3
import uuid
import zipfile
from contextlib import closing
from pathlib import Path
from cryptography.fernet import InvalidToken
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from vault.storage import cipher, VaultError


class Command(BaseCommand):
    help = 'Verify and restore an encrypted backup into a NEW external directory; never overwrite a live installation.'

    def add_arguments(self, parser):
        parser.add_argument('backup')
        parser.add_argument('destination')

    def handle(self, *args, **options):
        destination = Path(options['destination']).resolve()
        if destination.is_relative_to(settings.BASE_DIR) or destination.exists():
            raise CommandError('Choose a new destination outside the repository.')
        try:
            encrypted = Path(options['backup']).read_bytes()
            with zipfile.ZipFile(io.BytesIO(cipher().decrypt(encrypted))) as bundle:
                manifest = json.loads(bundle.read('manifest.json'))
                if manifest.get('format') != 1:
                    raise ValueError('Unsupported backup.')
                # Do not extract archive paths. Only known names are written to a new directory.
                destination.mkdir(mode=0o700, parents=True)
                database = destination / 'familyos.sqlite3'
                database.write_bytes(bundle.read('familyos.sqlite3'))
                database.chmod(0o600)
                with closing(sqlite3.connect(database)) as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Invalid database.')
                    rows = db.execute('SELECT storage_key, checksum, size FROM vault_document').fetchall()
                    if len(rows) != manifest['objects']:
                        raise ValueError('Incomplete backup.')
                    objects = destination / 'objects'
                    objects.mkdir(mode=0o700)
                    for key, checksum, size in rows:
                        name = str(uuid.UUID(key)) + '.enc'
                        blob = bundle.read('objects/' + name)
                        clear = cipher().decrypt(blob)
                        if len(clear) != size or hashlib.sha256(clear).hexdigest() != checksum:
                            raise ValueError('Invalid object.')
                        (objects / name).write_bytes(blob)
                        (objects / name).chmod(0o600)
                    # Restoring a backup must not resurrect old login sessions or Gmail grants.
                    db.execute('DELETE FROM django_session')
                    db.execute('DELETE FROM core_ownersession')
                    db.execute('DELETE FROM vault_oauthattempt')
                    db.execute("UPDATE vault_gmailconnection SET credentials='', connected=0, requested=0, status='disconnected', lease=NULL, lease_until=NULL, page_token=''")
                    db.commit()
        except (OSError, InvalidToken, zipfile.BadZipFile, ValueError, KeyError, sqlite3.Error, VaultError) as exc:
            raise CommandError('Restore failed. Do not use the destination; preserve the backup and check the key and integrity.') from exc
        self.stdout.write(self.style.SUCCESS('Restore verified. Set DATA_DIR to this directory and VAULT_ROOT to its objects directory. Reconnect Gmail.'))
