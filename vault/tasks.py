"""Owner-only, encrypted document tasks. No automatic payments or reminders."""
from django import forms
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from core.central import scoped
from core.models import AuditEvent
from core.record_forms import RevisionForm
from .models import DocumentTask
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
    due_on = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


def present(task):
    details = unseal(task.details)
    task.title = details['title']
    task.notes = details.get('notes', '')
    task.evidence = details.get('evidence', '')
    task.source_title = unseal(task.source_document.details)['title']
    return task


@require_GET
def task_list(request):
    completed = request.GET.get('completed') == '1'
    records = scoped(request, DocumentTask).filter(archived=False, completed=completed,
        source_document__family_id=request.owner_membership.family_id).select_related('source_document')
    page = Paginator(records, 20).get_page(request.GET.get('page'))
    for task in page:
        try:
            present(task)
            task.available = True
        except VaultError:
            task.title = 'Task temporarily unavailable'
            task.available = False
    return render(request, 'vault/tasks.html', {'page': page, 'completed': completed})


@require_http_methods(['GET', 'POST'])
def task_edit(request, task_id):
    task = get_object_or_404(scoped(request, DocumentTask), pk=task_id, archived=False,
        source_document__family_id=request.owner_membership.family_id)
    try:
        present(task)
        details = unseal(task.details)
    except VaultError:
        return HttpResponse('Task details are unavailable.', status=503)
    form = TaskForm(request.POST if request.method == 'POST' else None,
        initial={'title': task.title, 'notes': task.notes, 'due_on': task.due_on, 'revision': task.revision})
    status = 200
    if request.method == 'POST':
        status = 400
        if form.is_valid():
            details.update(title=form.cleaned_data['title'], notes=form.cleaned_data['notes'])
            with transaction.atomic():
                changed = scoped(request, DocumentTask).filter(pk=task.pk, revision=form.cleaned_data['revision']).update(
                    details=seal(details), due_on=form.cleaned_data['due_on'], revision=F('revision')+1, updated_at=timezone.now())
                if changed:
                    AuditEvent.objects.create(family_id=task.family_id, actor=request.user, action='task.updated')
            if changed:
                return redirect('task-list')
            form.add_error(None, 'This task changed. Reload before saving.')
            status = 409
    return render(request, 'vault/form.html', {'form': form, 'title': 'Edit document task', 'back_url': 'task-list'}, status=status)


@require_POST
def task_complete(request, task_id):
    task = get_object_or_404(scoped(request, DocumentTask), pk=task_id, archived=False,
        source_document__family_id=request.owner_membership.family_id)
    form = RevisionForm(request.POST)
    if not form.is_valid() or request.POST.get('completed') not in ('0', '1'):
        return HttpResponse('Invalid task update.', status=400)
    completed = request.POST['completed'] == '1'
    with transaction.atomic():
        changed = scoped(request, DocumentTask).filter(pk=task.pk, revision=form.cleaned_data['revision']).update(
            completed=completed, revision=F('revision')+1, updated_at=timezone.now())
        if changed:
            AuditEvent.objects.create(family_id=task.family_id, actor=request.user,
                action='task.completed' if completed else 'task.reopened')
    if not changed:
        return HttpResponse('This task changed. Reload before trying again.', status=409)
    return redirect('task-list')
