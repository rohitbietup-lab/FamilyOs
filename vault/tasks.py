"""Owner-only encrypted responsibilities, source-linked tasks and in-app reminders."""
import calendar
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from core.central import scoped
from core.models import AuditEvent
from core.record_forms import RevisionForm
from .models import DocumentTask, FamilyPerson, TaskCompletion
from .storage import VaultError, seal, unseal


def create_document_task(*, document, kind, title, notes, evidence, source_page=None, source_date=None):
    if document.archived:
        raise ValueError('Task sources must be active documents.')
    if not kind or len(kind) > 80 or not title or len(title) > 160 or len(notes) > 3000 or len(evidence) > 1500:
        raise ValueError('Invalid document task details.')
    if source_page is not None and not 1 <= source_page <= 500:
        raise ValueError('Invalid source page.')
    with transaction.atomic():
        task, created = DocumentTask.objects.get_or_create(family_id=document.family_id, kind=kind, defaults={
            'source_document': document, 'source_page': source_page, 'source_date': source_date,
            'details': seal({'title': title, 'notes': notes, 'evidence': evidence}),
        })
        if created:
            AuditEvent.objects.create(family_id=document.family_id, action='task.created')
    return task, created


class TaskForm(RevisionForm):
    title = forms.CharField(max_length=160)
    notes = forms.CharField(max_length=3000, required=False, widget=forms.Textarea)
    due_on = forms.DateField(required=False, label='Due date (optional)', widget=forms.DateInput(attrs={'type': 'date'}))
    assignee = forms.ModelChoiceField(queryset=FamilyPerson.objects.none(), required=False, empty_label='Owner')
    recurrence = forms.ChoiceField(choices=DocumentTask._meta.get_field('recurrence').choices, required=False)
    remind_days = forms.IntegerField(min_value=0, max_value=30, required=False, label='Show in reminders this many days before due')

    def __init__(self, *args, family_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = FamilyPerson.objects.filter(family_id=family_id, archived=False)
        self.fields['assignee'].label_from_instance = lambda person: person.name
        self.fields['assignee'].help_text = 'Labels alone do not grant sign-in. Assigning a linked adult shares this task title and notes; source documents and evidence require a separate document share.'

    def clean(self):
        values = super().clean()
        values['recurrence'] = values.get('recurrence') or 'none'
        values['remind_days'] = values.get('remind_days') or 0
        if values['recurrence'] != 'none' and not values.get('due_on'):
            self.add_error('due_on', 'Set a due date before choosing a repeat schedule.')
        return values


def task_today():
    return timezone.localdate(timezone=ZoneInfo(settings.TASK_TIME_ZONE))


def next_due(task):
    due = task.due_on
    if task.recurrence == 'daily':
        return due + timedelta(days=1)
    if task.recurrence == 'weekly':
        return due + timedelta(days=7)
    year, month = due.year, due.month
    if task.recurrence == 'monthly':
        year, month = year + (month == 12), month % 12 + 1
    elif task.recurrence == 'yearly':
        year += 1
    return date(year, month, min(task.recurrence_day or due.day, calendar.monthrange(year, month)[1]))


def visible_tasks(request):
    family_id = request.owner_membership.family_id
    return scoped(request, DocumentTask).filter(archived=False).filter(
        Q(source_document__isnull=True) | Q(source_document__family_id=family_id))


def reminder_summary(request):
    records = visible_tasks(request).filter(completed=False)
    today = task_today()
    candidates = records.filter(due_on__lte=today+timedelta(days=30)).select_related('source_document','assignee').order_by('due_on','id')
    reminders = []
    for task in candidates:
        if task.due_on <= today+timedelta(days=task.remind_days):
            reminders.append(task)
    for task in reminders[:5]:
        try:
            present(task)
        except VaultError:
            task.title = 'Task temporarily unavailable'
    return {'overdue': records.filter(due_on__lt=today).count(), 'today': records.filter(due_on=today).count(),
            'unscheduled': records.filter(due_on__isnull=True).count(), 'items': reminders[:5], 'count':len(reminders)}


def present(task):
    details = unseal(task.details)
    task.title = details['title']
    task.notes = details.get('notes', '')
    task.evidence = details.get('evidence', '')
    task.source_title = unseal(task.source_document.details)['title'] if task.source_document_id else ''
    return task


@require_GET
def task_list(request):
    completed = request.GET.get('completed') == '1'
    records = visible_tasks(request).filter(completed=completed).select_related('source_document','assignee')
    due_filter = request.GET.get('due','')
    today = task_today()
    if due_filter == 'overdue':
        records = records.filter(due_on__lt=today)
    elif due_filter == 'today':
        records = records.filter(due_on=today)
    elif due_filter == 'week':
        records = records.filter(due_on__range=(today,today+timedelta(days=7)))
    elif due_filter == 'unscheduled':
        records = records.filter(due_on__isnull=True)
    page = Paginator(records, 20).get_page(request.GET.get('page'))
    for task in page:
        try:
            present(task)
            task.available = True
            task.completion_count = task.completions.count()
        except VaultError:
            task.title = 'Task temporarily unavailable'
            task.available = False
    return render(request, 'vault/tasks.html', {'page': page, 'completed': completed,
        'due_filter': due_filter, 'reminders': reminder_summary(request)})


@require_http_methods(['GET', 'POST'])
def task_edit(request, task_id=None):
    task = get_object_or_404(visible_tasks(request), pk=task_id) if task_id else None
    try:
        if task:
            present(task)
        details = unseal(task.details) if task else {'evidence':''}
    except VaultError:
        return HttpResponse('Task details are unavailable.', status=503)
    initial = {'title': task.title, 'notes': task.notes, 'due_on': task.due_on, 'revision': task.revision,
        'assignee':task.assignee_id,'recurrence':task.recurrence,'remind_days':task.remind_days} if task else {'revision':1,'recurrence':'none','remind_days':0}
    form = TaskForm(request.POST if request.method == 'POST' else None, initial=initial,
        family_id=request.owner_membership.family_id)
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            details.update(title=form.cleaned_data['title'], notes=form.cleaned_data['notes'])
            due = form.cleaned_data['due_on']
            recurrence = form.cleaned_data['recurrence']
            anchor = task.recurrence_day if task and task.recurrence == recurrence and task.due_on == due else (due.day if due else None)
            values = dict(details=seal(details), due_on=due, assignee=form.cleaned_data['assignee'],
                recurrence=recurrence, recurrence_day=anchor, remind_days=form.cleaned_data['remind_days'])
            with transaction.atomic():
                if task:
                    changed = visible_tasks(request).filter(pk=task.pk, revision=form.cleaned_data['revision']).update(
                        **values, revision=F('revision')+1, updated_at=timezone.now())
                else:
                    task = DocumentTask.objects.create(family_id=request.owner_membership.family_id, kind='manual-'+str(uuid.uuid4()), **values)
                    changed = True
                if changed:
                    AuditEvent.objects.create(family_id=task.family_id, actor=request.user,
                        action='task.updated' if task_id else 'task.created')
            if changed:
                return redirect('task-list')
            form.add_error(None, 'This task changed. Reload before saving.')
            status = 409
    return render(request, 'vault/form.html', {'form': form, 'title': 'Edit task' if task_id else 'Add a task', 'back_url': 'task-list'}, status=status)


@require_POST
def task_complete(request, task_id):
    task = get_object_or_404(visible_tasks(request), pk=task_id)
    return complete_task(request, task, visible_tasks(request), 'task-list')


def complete_task(request, task, allowed, redirect_name):
    form = RevisionForm(request.POST)
    if not form.is_valid() or request.POST.get('completed') not in ('0', '1'):
        return HttpResponse('Invalid task update.', status=400)
    completed = request.POST['completed'] == '1'
    recurring = completed and task.recurrence != 'none'
    try:
        due = next_due(task) if recurring else task.due_on
    except (ValueError, OverflowError):
        return HttpResponse('The repeat schedule exceeds the supported date range. Edit the schedule first.', status=400)
    with transaction.atomic():
        changed = allowed.filter(pk=task.pk, revision=form.cleaned_data['revision'],completed=not completed).update(
            completed=False if recurring else completed, due_on=due, revision=F('revision')+1, updated_at=timezone.now())
        if changed:
            if completed:
                TaskCompletion.objects.create(task=task, revision=task.revision, scheduled_on=task.due_on)
            AuditEvent.objects.create(family_id=task.family_id, actor=request.user,
                action='task.completed' if completed else 'task.reopened')
    if not changed:
        return HttpResponse('This task changed. Reload before trying again.', status=409)
    if recurring:
        messages.success(request, 'Occurrence completed. The task now shows its next scheduled date.')
    return redirect(redirect_name)
