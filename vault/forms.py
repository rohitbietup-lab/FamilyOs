from django import forms
from .models import Category, FamilyPerson


class DocumentForm(forms.Form):
    title = forms.CharField(max_length=160)
    category = forms.ChoiceField(choices=Category.choices)
    person = forms.ModelChoiceField(queryset=FamilyPerson.objects.none(), required=False, label='Family member')
    expires_on = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    renew_on = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    starred = forms.BooleanField(required=False, label='Important / starred')
    notes = forms.CharField(max_length=1000, required=False, widget=forms.Textarea)
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput, initial=1)

    def __init__(self, *args, family_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['person'].queryset = FamilyPerson.objects.filter(family_id=family_id, archived=False)
        self.fields['person'].label_from_instance = lambda person: person.name


class UploadForm(DocumentForm):
    file = forms.FileField(help_text='PDF, PNG or JPEG; maximum 10 MiB. Password-protected PDFs are not supported.')


class PersonForm(forms.Form):
    name = forms.CharField(max_length=100)
