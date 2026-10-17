from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import Family, Membership
from .access import eligible_member


class OwnerLoginForm(AuthenticationForm):
    username = forms.EmailField(label='Email', max_length=150, widget=forms.EmailInput(attrs={'autocomplete': 'username', 'autofocus': True}))

    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        member = Membership.objects.filter(user=user,active=True).select_related('user','person').first()
        if not eligible_member(member):
            raise self.get_invalid_login_error()


class ProfileForm(forms.Form):
    display_name = forms.CharField(max_length=150, label='Your name')


class FamilyForm(forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Family
        fields = ['name', 'mission', 'revision']
        widgets = {'mission': forms.Textarea(attrs={'rows': 3})}
