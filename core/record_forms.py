from datetime import date
from decimal import Decimal
from django import forms
from django.utils import timezone
from .models import FinancialRecord, Goal


class FinancialRecordForm(forms.Form):
    name = forms.CharField(max_length=120, label='Record name')
    kind = forms.ChoiceField(choices=FinancialRecord.Kind.choices)
    category = forms.ChoiceField(choices=FinancialRecord.Category.choices)
    amount = forms.DecimalField(label='Value (INR)', min_value=Decimal('0.00'), max_value=Decimal('9999999999999.99'), decimal_places=2, max_digits=15,
        help_text='Enter the current value or outstanding balance in rupees, with up to two decimal places.')
    valued_on = forms.DateField(label='Valuation date', widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='The date this value was checked. Future valuations are not accepted.')
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional context. Do not enter account passwords or full account numbers.')
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean_valued_on(self):
        value = self.cleaned_data['valued_on']
        if value > timezone.localdate() or value < date(1900, 1, 1):
            raise forms.ValidationError('Use a date between 1 January 1900 and today.')
        return value

    def clean(self):
        data = super().clean()
        valid = {'asset': {'cash', 'investment', 'property', 'retirement', 'other'}, 'liability': {'loan', 'mortgage', 'credit', 'other'}}
        if data.get('kind') in valid and data.get('category') not in valid[data['kind']]:
            self.add_error('category', 'Choose a category that matches the asset or liability type.')
        return data

    def record_values(self):
        return {**{k: self.cleaned_data[k] for k in ['name', 'kind', 'category', 'valued_on', 'notes']},
                'value_paise': int(self.cleaned_data['amount'] * 100)}


class GoalForm(forms.Form):
    title = forms.CharField(max_length=160)
    area = forms.ChoiceField(choices=Goal.Area.choices)
    target_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    progress = forms.IntegerField(min_value=0, max_value=100, label='Progress (%)',
        help_text='A manual estimate of progress, not an automatic calculation from your finances.')
    status = forms.ChoiceField(choices=Goal.Status.choices)
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 3}))
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean_target_date(self):
        value = self.cleaned_data['target_date']
        if not date(1900, 1, 1) <= value <= date(2200, 12, 31):
            raise forms.ValidationError('Use a year between 1900 and 2200.')
        return value

    def clean(self):
        data = super().clean()
        progress, status = data.get('progress'), data.get('status')
        if progress is not None and status:
            if progress == 100:
                data['status'] = Goal.Status.COMPLETED
            elif status == Goal.Status.COMPLETED:
                self.add_error('progress', 'Completed goals must have 100% progress.')
        return data

    def record_values(self):
        return {k: self.cleaned_data[k] for k in ['title', 'area', 'target_date', 'progress', 'status', 'notes']}


class RevisionForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
