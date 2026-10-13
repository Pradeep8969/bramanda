"""Shared post-login navigation; destination checks never grant permissions."""

from urllib.parse import unquote, urlsplit

from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .models import User


def role_home(user):
    if user.is_active and user.role == User.Role.OWNER:
        return reverse("owner:home")
    if user.is_active and user.role == User.Role.STAFF:
        return reverse("dashboard:home")
    return reverse("home")


def safe_login_next(request, destination, user=None):
    if not destination or not url_has_allowed_host_and_scheme(
        destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return False
    # Normalize encoded paths for permission checks and reject ambiguous paths.
    path = unquote(urlsplit(destination).path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or any(part in (".", "..") for part in path.split("/"))
    ):
        return False
    try:
        match = resolve(path)
    except Resolver404:
        return False
    if match.namespace == "admin":
        return False
    if match.namespace in ("owner", "dashboard"):
        # OAuth collects next before identity is known; post_login checks again.
        if user is not None and user.is_authenticated:
            roles = (
                (User.Role.OWNER,)
                if match.namespace == "owner"
                else (User.Role.OWNER, User.Role.STAFF)
            )
            if not user.is_active or user.role not in roles:
                return False
        if match.url_name not in {
            "home",
            "reports",
            "staff",
            "staff_add",
            "staff_edit",
            "payments",
            "activity",
            "customers",
            "inventory",
            "orders",
            "order_detail",
            "cancellations",
            "products",
            "categories",
            "sizes",
            "colors",
            "variants",
            "products_add",
            "products_edit",
            "categories_add",
            "categories_edit",
            "sizes_add",
            "sizes_edit",
            "colors_add",
            "colors_edit",
            "variants_add",
            "variants_edit",
        }:
            return False
    if match.namespace == "accounts" and match.url_name != "profile":
        return False
    if (
        not match.namespace
        and match.url_name != "home"
        and match.url_name.startswith(("account_", "socialaccount_", "google_"))
    ):
        return False
    if (
        user is not None
        and user.is_authenticated
        and user.role in (User.Role.OWNER, User.Role.STAFF)
    ):
        if match.view_name in ("home", "products:shop"):
            return False
    return True


def login_destination(request, destination=None):
    return (
        destination
        if safe_login_next(request, destination, request.user)
        else role_home(request.user)
    )
