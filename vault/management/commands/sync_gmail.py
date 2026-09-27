import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from vault.sync import run_page


class Command(BaseCommand):
    help = 'Process queued Gmail document pages. Run continuously under a process supervisor.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one page and exit.')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            processed = run_page()
            if options['once']:
                return
            if not processed:
                time.sleep(5)
