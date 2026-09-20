from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from core.models import AuditEvent, Family, Membership, Role


class Command(BaseCommand):
    help = 'Create the single owner interactively. Never put passwords in command arguments.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--family', required=True)

    def handle(self, *args, **options):
        if Family.objects.exists():
            raise CommandError('An owner/family already exists. Bootstrap cannot replace it.')
        email = options['email'].strip().lower()
        try:
            validate_email(email)
            if len(email) > 150:
                raise ValidationError('Email must be at most 150 characters.')
            if not 1 <= len(options['name'].strip()) <= 150 or not 1 <= len(options['family'].strip()) <= 100:
                raise ValidationError('Provide a name (1–150 characters) and family name (1–100).')
            user = get_user_model()(username=email, email=email, first_name=options['name'].strip())
            password = getpass('Owner password (12+ characters): ')
            if password != getpass('Confirm password: '):
                raise CommandError('Passwords did not match.')
            validate_password(password, user)
            with transaction.atomic():
                family = Family.objects.create(id=1, name=options['family'].strip())
                user.set_password(password)
                user.save()
                Membership.objects.create(user=user, family=family, role=Role.OWNER)
                AuditEvent.objects.create(actor=user, family=family, action='owner.bootstrapped')
        except (ValidationError, IntegrityError) as exc:
            raise CommandError('Owner setup rejected: ' + str(exc)) from exc
        self.stdout.write(self.style.SUCCESS('Owner created. You can now sign in.'))
