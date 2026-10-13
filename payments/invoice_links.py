"""Seven-day bearer links, scoped to one order and its customer."""

from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

MAX_AGE = 7 * 24 * 60 * 60
SALT = "bramanda.payments.invoice.v1"


def signer():
    if not settings.INVOICE_SIGNING_KEY:
        raise ImproperlyConfigured(
            "INVOICE_SIGNING_KEY is required for email invoice links."
        )
    return signing.TimestampSigner(
        key=settings.INVOICE_SIGNING_KEY, salt=SALT, fallback_keys=[]
    )


def public_origin():
    origin = settings.BRAMANDA_PUBLIC_BASE_URL
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or ord(character) < 32 for character in origin)
    ):
        raise ImproperlyConfigured(
            "BRAMANDA_PUBLIC_BASE_URL must be an HTTP(S) origin without a path or credentials."
        )
    try:
        parsed.port
    except ValueError:
        raise ImproperlyConfigured(
            "BRAMANDA_PUBLIC_BASE_URL has an invalid port."
        ) from None
    return origin


def invoice_url(order):
    token = signer().sign_object(
        {"order": order.pk, "customer": order.customer_id, "number": order.order_number}
    )
    return public_origin() + reverse("payments:signed_invoice", args=[token])


def invoice_identity(token):
    identity = signer().unsign_object(token, max_age=MAX_AGE)
    if (
        not isinstance(identity, dict)
        or set(identity) != {"order", "customer", "number"}
        or type(identity["order"]) is not int
        or type(identity["customer"]) is not int
        or not isinstance(identity["number"], str)
    ):
        raise signing.BadSignature("Invalid invoice identity.")
    return identity


def validate_invoice_url(url, order):
    """Validate the final email parameter, including any configured variable aliases."""
    if not isinstance(url, str):
        raise signing.BadSignature("Missing invoice URL.")
    prefix = public_origin() + reverse(
        "payments:signed_invoice", args=["TOKEN"]
    ).replace("TOKEN/", "")
    if not url.startswith(prefix) or not url.endswith("/"):
        raise signing.BadSignature("Invalid invoice URL.")
    token = url[len(prefix) : -1]
    if invoice_identity(token) != {
        "order": order.pk,
        "customer": order.customer_id,
        "number": order.order_number,
    }:
        raise signing.BadSignature("Invoice identity mismatch.")
