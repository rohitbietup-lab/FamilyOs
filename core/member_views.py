from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST
from .access import accessible_documents, assigned_tasks
from vault.storage import unseal, VaultError
from vault.tasks import complete_task


@require_GET
def home(request):
    member=request.family_membership
    return render(request,'core/member_home.html',{'family_name':member.family.name,
        'task_count':assigned_tasks(member).filter(completed=False).count(),
        'document_count':accessible_documents(member).count()})


@require_GET
def tasks(request):
    member=request.family_membership
    completed=request.GET.get('completed')=='1'
    records=assigned_tasks(member).filter(completed=completed).select_related('source_document')
    page=Paginator(records,20).get_page(request.GET.get('page'))
    shared=set(accessible_documents(member).values_list('pk',flat=True))
    for task in page:
        task.available=False
        task.can_view_source=bool(task.source_document_id and task.source_document_id in shared)
        try:
            details=unseal(task.details)
            task.title=details['title']
            task.notes=details.get('notes','')
            task.available=True
            if task.can_view_source:
                task.evidence=details.get('evidence','')
                task.source_title=unseal(task.source_document.details)['title']
        except VaultError:
            task.title='Task temporarily unavailable'
    return render(request,'core/member_tasks.html',{'page':page,'completed':completed})


@require_POST
def task_complete(request,task_id):
    if request.POST.get('completed')!='1':
        return HttpResponseBadRequest('Only completion of an assigned task is supported.')
    allowed=assigned_tasks(request.family_membership)
    task=get_object_or_404(allowed,pk=task_id)
    return complete_task(request,task,allowed,'member-tasks')


@require_GET
def documents(request):
    page=Paginator(accessible_documents(request.family_membership),20).get_page(request.GET.get('page'))
    for doc in page:
        try:
            doc.title=unseal(doc.details)['title']
        except VaultError:
            doc.title='Document temporarily unavailable'
    return render(request,'core/member_documents.html',{'page':page})
