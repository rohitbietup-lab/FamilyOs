import sqlite3
from contextlib import closing
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create a consistent SQLite backup outside the repository; never overwrite a file.'

    def add_arguments(self, parser):
        parser.add_argument('destination')

    def handle(self, *args, **options):
        destination = Path(options['destination']).resolve()
        if destination.is_relative_to(settings.BASE_DIR):
            raise CommandError('Backups contain private data: choose a location outside the repository.')
        source = Path(settings.DATABASES['default']['NAME']).resolve()
        if not source.exists():
            raise CommandError('Database missing. Run migrations first.')
        try:
            with destination.open('xb'):
                pass
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise CommandError('Backup failed integrity verification.')
        except (OSError, sqlite3.Error) as exc:
            raise CommandError('Backup failed: ' + str(exc)) from exc
        self.stdout.write(self.style.SUCCESS('Backup created and integrity verified. Protect it like the live database.'))
