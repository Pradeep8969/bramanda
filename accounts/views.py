from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_http_methods

from orders.models import Order

from .emails import schedule_welcome_email
from .forms import ProfileForm, RegistrationForm
from .redirects import login_destination


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        schedule_welcome_email(user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(
            request, "Welcome to BRAMANDA! Your customer account is ready."
        )
        return redirect("products:shop")
    return render(request, "accounts/register.html", {"form": form})


class CustomerLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        destination = self.request.POST.get(
            self.redirect_field_name, self.request.GET.get(self.redirect_field_name)
        )
        return login_destination(self.request, destination)

    def form_valid(self, form):
        messages.success(self.request, "Welcome back to BRAMANDA.")
        return super().form_valid(form)


class CustomerLogoutView(LogoutView):
    next_page = reverse_lazy("home")

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.success(request, "You have been logged out.")
        return response


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(
        request.POST if request.method == "POST" else None, instance=request.user
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("accounts:profile")
    if request.method == "POST":
        # ModelForm validation can mutate its instance even when invalid.
        # Keep the identity/completion based on saved data; bound inputs retain edits.
        request.user.refresh_from_db()
    return render(request, "accounts/profile.html", profile_context(request.user, form))


def profile_context(user, form):
    first, last = user.first_name.strip(), user.last_name.strip()
    name = user.get_full_name().strip() or user.username.strip() or "Your account"
    initials = ((first[:1] + last[:1]) or user.username.strip()[:2] or "B").upper()
    email_verified = (
        bool(user.email.strip())
        and EmailAddress.objects.filter(
            user=user, email__iexact=user.email.strip(), verified=True
        ).exists()
    )
    checks = [
        (bool(first), "Add your first name to complete your profile."),
        (bool(last), "Add your last name to complete your profile."),
        (
            email_verified,
            (
                "Your email is not yet verified."
                if user.email.strip()
                else "Add your email address to complete your profile."
            ),
        ),
        (
            bool(user.phone_number.strip()),
            "Add your phone number to complete your profile.",
        ),
        (bool(user.address.strip()), "Add your address to complete your profile."),
    ]
    # On invalid submissions, never label a newly entered email as verified.
    displayed_email = str(form["email"].value() or "").strip()
    verified_badge = (
        email_verified and displayed_email.casefold() == user.email.strip().casefold()
    )
    latest_order = (
        Order.objects.filter(customer=user).order_by("-created_at", "-pk").first()
    )
    recent_item, recent_image = None, None
    if latest_order:
        recent_item = (
            latest_order.items.select_related("product")
            .prefetch_related("product__images")
            .first()
        )
        if recent_item and recent_item.product:
            product = recent_item.product
            if product.image:
                recent_image = product.image
            else:
                gallery = next(iter(product.images.all()), None)
                if gallery:
                    recent_image = gallery.image
    return {
        "form": form,
        "profile_name": name,
        "profile_initials": initials,
        "profile_completion": sum(complete for complete, _ in checks) * 20,
        "completion_hint": next(
            (hint for complete, hint in checks if not complete),
            "Your profile is complete.",
        ),
        "email_verified": verified_badge,
        "google_linked": SocialAccount.objects.filter(
            user=user, provider="google"
        ).exists(),
        "recent_order": latest_order,
        "recent_item": recent_item,
        "recent_image": recent_image,
    }
