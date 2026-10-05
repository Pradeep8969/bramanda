from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class StaffCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'is_active')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'STAFF'
        if commit:
            user.save()
        return user


class StaffEditForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'is_active')


class ReportFilterForm(forms.Form):
    from_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    to_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('from_date') and data.get('to_date') and data['from_date'] > data['to_date']:
            raise forms.ValidationError('From date must be before or equal to to date.')
        return data
