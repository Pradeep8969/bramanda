from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from .models import User
from .redirects import login_destination, role_home, safe_login_next


class CustomerAccountAdapter(DefaultAccountAdapter):
    """Use the same role-aware navigation as password login."""

    def is_safe_url(self, url):
        return safe_login_next(self.request, url, self.request.user)

    def get_login_redirect_url(self, request):
        return role_home(request.user)

    def post_login(self, request, user, *, redirect_url=None, **kwargs):
        # Revalidate OAuth state after login, when the actual role is known.
        destination = redirect_url or request.POST.get("next", request.GET.get("next"))
        return super().post_login(
            request,
            user,
            redirect_url=login_destination(request, destination),
            **kwargs,
        )


class CustomerSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Enforce least privilege at creation, without changing returning users."""

    def save_user(self, request, sociallogin, form=None):
        # allauth calls this hook for signup, not login or account connection.
        if sociallogin.user.pk is None:
            sociallogin.user.role = User.Role.CUSTOMER
            sociallogin.user.is_staff = False
            sociallogin.user.is_superuser = False
        return super().save_user(request, sociallogin, form=form)
