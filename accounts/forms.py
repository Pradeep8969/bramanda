from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.forms import _unicode_ci_compare
from django.conf import settings
from urllib.parse import urlsplit

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, max_length=254,
                             widget=forms.EmailInput(attrs={'autocomplete': 'email'}))

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account already uses this email address. Please sign in instead.')
        return email

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'address')
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CUSTOMER
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone_number', 'address')
        widgets = {'address': forms.Textarea(attrs={'rows': 3})}


class CustomerPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        email_field = User.get_email_field_name()
        # Social-only customers choose their first local password through the
        # same secure confirmation flow; Django's default lookup excludes them.
        customers = User._default_manager.filter(**{
            f'{email_field}__iexact': email,
            'is_active': True,
            'role': User.Role.CUSTOMER,
        }).exclude(**{email_field: ''})
        return (user for user in customers
                if _unicode_ci_compare(email, getattr(user, email_field)))

    def save(self, **kwargs):
        origin = urlsplit(settings.PUBLIC_BASE_URL)
        kwargs['domain_override'] = origin.netloc
        kwargs['use_https'] = origin.scheme == 'https'
        return super().save(**kwargs)

