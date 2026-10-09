from urllib.parse import unquote, urlsplit

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import Resolver404, resolve

from .models import User


class CustomerAccountAdapter(DefaultAccountAdapter):
    """Keep allauth redirects out of management areas."""

    def is_safe_url(self, url):
        if not super().is_safe_url(url):
            return False
        path = unquote(urlsplit(url).path)
        try:
            match = resolve(path)
        except Resolver404:
            return False
        return match.namespace not in {'owner', 'dashboard', 'admin'}


class CustomerSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Enforce least privilege at creation, without changing returning users."""

    def save_user(self, request, sociallogin, form=None):
        # allauth calls this hook for signup, not login or account connection.
        if sociallogin.user.pk is None:
            sociallogin.user.role = User.Role.CUSTOMER
            sociallogin.user.is_staff = False
            sociallogin.user.is_superuser = False
        return super().save_user(request, sociallogin, form=form)
