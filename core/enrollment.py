"""Email-bound, one-use adult invitations. Delivery requires explicit owner POST."""
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from .access import eligible_member
from .models import AuditEvent, Invitation, Membership, Role


class EnrollmentError(Exception):
    pass


def enrollment_ready():
    origin=urlsplit(settings.FAMILY_PUBLIC_ORIGIN)
    return bool(settings.FAMILY_ENROLLMENT_ENABLED and not settings.DEVELOPMENT
        and origin.scheme=='https' and origin.hostname in settings.ALLOWED_HOSTS
        and not origin.username and not origin.password and origin.path in ('','/')
        and not origin.query and not origin.fragment and settings.EMAIL_HOST
        and settings.DEFAULT_FROM_EMAIL and settings.EMAIL_BACKEND=='django.core.mail.backends.smtp.EmailBackend'
        and settings.EMAIL_USE_TLS)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_invitation(*,owner,email,person):
    if not enrollment_ready() or not eligible_member(owner) or owner.role!=Role.OWNER:
        raise EnrollmentError('Enrollment needs operator setup before invitations can be sent.')
    email=email.strip().lower()
    if person.family_id!=owner.family_id or person.archived or Membership.objects.filter(person=person).exists():
        raise EnrollmentError('Choose an unlinked active family label.')
    if get_user_model().objects.filter(username__iexact=email).exists() or get_user_model().objects.filter(email__iexact=email).exists():
        raise EnrollmentError('This address cannot be invited. Ask the operator to review existing accounts.')
    token=secrets.token_urlsafe(32)
    code=f'{secrets.randbelow(100000000):08d}'
    now=timezone.now()
    with transaction.atomic():
        if Invitation.objects.filter(family=owner.family,created_at__gt=now-timedelta(days=1)).exclude(status='disabled').count()>=10:
            raise EnrollmentError('Invitation limit reached. Try again tomorrow.')
        Invitation.objects.filter(family=owner.family,status='pending').filter(Q(email__iexact=email)|Q(person=person)).update(status='revoked',verification_digest='')
        invitation=Invitation.objects.create(family=owner.family,email=email,role=Role.ADULT,status='pending',person=person,
            token_digest=digest(token),verification_digest=digest(token+':'+code),expires_at=now+timedelta(hours=48))
    link=settings.FAMILY_PUBLIC_ORIGIN.rstrip('/')+'/join/#token='+token
    try:
        sent=send_mail('Your FamilyOS adult invitation',
            'An owner invited this email address to FamilyOS. This link expires in 48 hours.\n\n'+link+
            '\n\nVerification code: '+code+'\n\nOpen the link, enter this email address and code, and choose your own password. '
            'Only explicitly assigned tasks and shared documents will be available.',settings.DEFAULT_FROM_EMAIL,[email],fail_silently=False)
        if sent!=1:
            raise EnrollmentError('Delivery was not confirmed.')
    except Exception:
        Invitation.objects.filter(pk=invitation.pk,status='pending').update(status='revoked',verification_digest='')
        raise EnrollmentError('Invitation delivery failed. Check operator email settings.') from None
    AuditEvent.objects.create(family=owner.family,actor=owner.user,action='invitation.sent')
    return invitation


def accept_invitation(*,token,code,email,name,password):
    if not enrollment_ready() or len(token)>128 or len(code)>16:
        raise EnrollmentError('Invitation cannot be accepted. Check the email or ask the owner for a new invitation.')
    email=email.strip().lower()
    with transaction.atomic():
        inv=Invitation.objects.select_for_update().filter(token_digest=digest(token),status='pending').select_related('person','family').first()
        if not inv or not inv.expires_at or inv.expires_at<=timezone.now() or inv.attempts>=5:
            raise EnrollmentError('Invitation cannot be accepted. Check the email or ask the owner for a new invitation.')
        valid=bool(inv.role==Role.ADULT and inv.email==email and inv.person_id and not inv.person.archived
            and inv.person.family_id==inv.family_id and not Membership.objects.filter(person=inv.person).exists()
            and Membership.objects.filter(family=inv.family,role=Role.OWNER,active=True,user__is_active=True).exists()
            and constant_time_compare(inv.verification_digest,digest(token+':'+code)))
        if not valid:
            inv.attempts+=1
            inv.save(update_fields=['attempts'])
        else:
            User=get_user_model()
            if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
                valid=False
            if valid:
                user=User(username=email,email=email,first_name=name)
                validate_password(password,user)
                user.set_password(password)
                user.save()
                Membership.objects.create(user=user,family=inv.family,role=Role.ADULT,person=inv.person)
                inv.status='accepted'
                inv.accepted_at=timezone.now()
                inv.verification_digest=''
                inv.save(update_fields=['status','accepted_at','verification_digest'])
                AuditEvent.objects.create(family=inv.family,actor=user,action='invitation.accepted')
                return user
    # Raise after committing failed attempt counters, not inside the transaction.
    raise EnrollmentError('Invitation cannot be accepted. Check the email or ask the owner for a new invitation.')
