"""Owner-scoped central records; all mutations preserve history through archive/restore."""
from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from .models import AuditEvent, FinancialRecord, Goal
from .record_forms import FinancialRecordForm, GoalForm, RevisionForm


def scoped(request, model):
    return model.objects.filter(family_id=request.owner_membership.family_id)


def finance_summary(records):
    # Python integer sums avoid both binary floating point and SQL integer overflow.
    rows = list(records.filter(archived=False).values('kind', 'value_paise', 'valued_on'))
    assets = sum(row['value_paise'] for row in rows if row['kind'] == 'asset')
    liabilities = sum(row['value_paise'] for row in rows if row['kind'] == 'liability')
    dates = [row['valued_on'] for row in rows]
    return {'assets': assets, 'liabilities': liabilities, 'net_worth': assets-liabilities,
            'count': len(rows), 'oldest_date': min(dates) if dates else None,
            'latest_date': max(dates) if dates else None}


def dashboard_data(request):
    goals = scoped(request, Goal).filter(archived=False)
    return {
        'finance': finance_summary(scoped(request, FinancialRecord)),
        'active_goals': goals.filter(status=Goal.Status.ACTIVE).count(),
        'completed_goals': goals.filter(status=Goal.Status.COMPLETED).count(),
        'overdue_goals': goals.filter(status=Goal.Status.ACTIVE, target_date__lt=timezone.localdate()).count(),
        'upcoming_goals': goals.filter(status=Goal.Status.ACTIVE)[:4],
    }


@require_GET
def finance_list(request):
    archived = request.GET.get('archived') == '1'
    records = scoped(request, FinancialRecord).filter(archived=archived)
    return render(request, 'core/finance.html', {
        'page': Paginator(records, 20).get_page(request.GET.get('page')),
        'archived': archived, 'finance': finance_summary(scoped(request, FinancialRecord)),
    })


@require_GET
def goals_list(request):
    archived = request.GET.get('archived') == '1'
    goals = scoped(request, Goal).filter(archived=archived)
    return render(request, 'core/goals.html', {
        'page': Paginator(goals, 20).get_page(request.GET.get('page')), 'archived': archived,
    })


def edit_record(request, model, form_class, kind, record_id=None):
    record = get_object_or_404(scoped(request, model), pk=record_id, archived=False) if record_id else None
    initial = {'revision': 1, 'valued_on': timezone.localdate(), 'progress': 0, 'status': Goal.Status.ACTIVE}
    if record:
        initial = {field: getattr(record, field, None) for field in form_class.base_fields}
        if kind == 'finance':
            initial['amount'] = Decimal(record.value_paise) / 100
    form = form_class(request.POST if request.method == 'POST' else None, initial=initial)
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                if record:
                    changed = scoped(request, model).filter(pk=record.pk, revision=form.cleaned_data['revision'], archived=False).update(
                        **form.record_values(), revision=F('revision')+1, updated_at=timezone.now())
                else:
                    scoped(request, model).create(family_id=request.owner_membership.family_id, **form.record_values())
                    changed = True
                if changed:
                    AuditEvent.objects.create(actor=request.user, family_id=request.owner_membership.family_id, action=f'{kind}.updated' if record else f'{kind}.created')
            if changed:
                messages.success(request, 'Changes saved.' if record else 'Record added.')
                return redirect('finance-list' if kind == 'finance' else 'goals-list')
            form.add_error(None, 'This record changed in another session. Reload this page before saving again.')
            status = 409
        else:
            status = 400
    noun = 'financial record' if kind == 'finance' else 'goal'
    return render(request, 'core/record_edit.html', {
        'form': form, 'title': ('Edit ' if record else 'Add ') + noun,
        'back_url': 'finance-list' if kind == 'finance' else 'goals-list',
    }, status=status)


@require_http_methods(['GET', 'POST'])
def finance_edit(request, record_id=None):
    return edit_record(request, FinancialRecord, FinancialRecordForm, 'finance', record_id)


@require_http_methods(['GET', 'POST'])
def goal_edit(request, record_id=None):
    return edit_record(request, Goal, GoalForm, 'goal', record_id)


def archive_record(request, model, kind, record_id, restore):
    record = get_object_or_404(scoped(request, model), pk=record_id)
    form = RevisionForm(request.POST if request.method == 'POST' else None, initial={'revision': record.revision})
    action = 'Restore' if restore else 'Archive'
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                changed = scoped(request, model).filter(pk=record.pk, revision=form.cleaned_data['revision'], archived=restore).update(
                    archived=not restore, revision=F('revision')+1, updated_at=timezone.now())
                if changed:
                    AuditEvent.objects.create(actor=request.user, family_id=request.owner_membership.family_id, action=f'{kind}.restored' if restore else f'{kind}.archived')
            if changed:
                messages.success(request, 'Record restored.' if restore else 'Record archived. You can restore it from the archive.')
                return redirect('finance-list' if kind == 'finance' else 'goals-list')
            form.add_error(None, 'This record has changed. Reload before trying again.')
            status = 409
        else:
            status = 400
    return render(request, 'core/archive.html', {'form': form, 'action': action,
        'record_name': record.name if kind == 'finance' else record.title,
        'restore': restore, 'back_url': 'finance-list' if kind == 'finance' else 'goals-list'}, status=status)


@require_http_methods(['GET', 'POST'])
def finance_archive(request, record_id, restore=False):
    return archive_record(request, FinancialRecord, 'finance', record_id, restore)


@require_http_methods(['GET', 'POST'])
def goal_archive(request, record_id, restore=False):
    return archive_record(request, Goal, 'goal', record_id, restore)


@require_GET
def api_summary(request):
    data = dashboard_data(request)
    finance = data['finance']
    # Money is serialized as strings so JavaScript consumers cannot lose integer precision.
    return JsonResponse({'currency': 'INR', 'finance': {
        'assets_paise': str(finance['assets']), 'liabilities_paise': str(finance['liabilities']),
        'net_worth_paise': str(finance['net_worth']), 'record_count': finance['count'],
        'oldest_valuation': finance['oldest_date'], 'latest_valuation': finance['latest_date'],
    }, 'goals': {'active': data['active_goals'], 'completed': data['completed_goals'], 'overdue': data['overdue_goals']}})
