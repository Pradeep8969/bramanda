import base64
import binascii
import hashlib
import hmac
import json
import socket
from decimal import Decimal, InvalidOperation
from time import monotonic

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse

REQUEST_FIELDS = "total_amount,transaction_uuid,product_code"
RESPONSE_FIELDS = "transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names"

ERROR_MESSAGES = {
    "DNS_ERROR": "BRAMANDA could not resolve the eSewa UAT verification host. Payment is unresolved; please retry or contact support.",
    "TLS_ERROR": "A secure connection to eSewa UAT could not be established. Please retry or contact support.",
    "PROXY_ERROR": "The server proxy could not connect to eSewa UAT. Please retry or contact support.",
    "NETWORK_ERROR": "BRAMANDA could not connect to eSewa UAT. Please try checking again.",
    "CONNECT_TIMEOUT": "Connecting to eSewa UAT timed out. Please try checking again.",
    "READ_TIMEOUT": "eSewa UAT took too long to respond. Please try checking again.",
    "TIMEOUT": "The eSewa UAT status check timed out. Please try checking again.",
    "HTTP_AUTH": "eSewa UAT rejected verification access. Please contact BRAMANDA; do not pay again.",
    "HTTP_NOT_FOUND": "The configured eSewa UAT verification endpoint was not found. Please contact BRAMANDA.",
    "HTTP_REDIRECT": "eSewa UAT redirected the verification request unexpectedly. Please retry or contact support.",
    "HTTP_ERROR": "eSewa UAT returned an HTTP error during verification. Please retry or contact support.",
    "INVALID_JSON": "eSewa UAT returned an unreadable status response. Please try checking again.",
    "MALFORMED_RESPONSE": "eSewa UAT returned an incomplete or invalid status response. Please retry or contact support.",
    "PROVIDER_UNAVAILABLE": "eSewa UAT reports that verification is temporarily unavailable. Please try checking again.",
    "PROVIDER_REJECTED": "eSewa UAT rejected the status request. Please contact BRAMANDA; do not pay again.",
    "UUID_MISMATCH": "The eSewa transaction ID does not match this payment. Please contact BRAMANDA; do not pay again.",
    "MERCHANT_MISMATCH": "The eSewa merchant does not match this payment. Please contact BRAMANDA; do not pay again.",
    "AMOUNT_MISMATCH": "The eSewa amount does not match this payment. Please contact BRAMANDA; do not pay again.",
    "REFERENCE_MISMATCH": "The eSewa transaction reference does not match this payment. Please contact BRAMANDA.",
    "UNKNOWN_STATUS": "eSewa UAT returned an unrecognized status. Payment is unresolved; please try checking again.",
    "CALLBACK_PAYLOAD": "The eSewa return data could not be read. Use Verify Payment to check this attempt safely.",
    "CALLBACK_SIGNATURE": "The eSewa return signature could not be verified. Use Verify Payment or contact BRAMANDA.",
}


class VerificationError(ValidationError):
    def __init__(self, error_code, diagnostics=None):
        self.error_code = error_code
        self.diagnostics = diagnostics or {}
        super().__init__(ERROR_MESSAGES[error_code], code=error_code)


def network_error_code(error):
    if isinstance(error, requests.exceptions.SSLError):
        return "TLS_ERROR"
    if isinstance(error, requests.exceptions.ProxyError):
        return "PROXY_ERROR"
    if isinstance(error, requests.ConnectTimeout):
        return "CONNECT_TIMEOUT"
    if isinstance(error, requests.ReadTimeout):
        return "READ_TIMEOUT"
    if isinstance(error, requests.Timeout):
        return "TIMEOUT"
    # requests wraps urllib3/socket exceptions. Inspect types, never URL-bearing messages.
    pending, seen = [error], set()
    while pending and len(seen) < 30:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if (
            isinstance(current, socket.gaierror)
            or type(current).__name__ == "NameResolutionError"
        ):
            return "DNS_ERROR"
        for nested in (
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
            getattr(current, "reason", None),
            *getattr(current, "args", ()),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return "NETWORK_ERROR"


def signature(message):
    if not settings.ESEWA_SECRET_KEY:
        raise ValidationError("Configure the eSewa UAT signing key before paying.")
    return base64.b64encode(
        hmac.new(
            settings.ESEWA_SECRET_KEY.encode(), message.encode(), hashlib.sha256
        ).digest()
    ).decode()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Invalid payment amount.")


def form_fields(payment):
    order = payment.order
    if (
        payment.amount != order.grand_total
        or order.subtotal + order.shipping_cost != order.grand_total
    ):
        raise ValidationError("Payment and order totals do not reconcile.")
    total = format(payment.amount, ".2f")
    fields = {
        "amount": format(order.subtotal, ".2f"),
        "tax_amount": "0",
        "product_service_charge": "0",
        "product_delivery_charge": format(order.shipping_cost, ".2f"),
        "total_amount": total,
        "transaction_uuid": str(payment.transaction_uuid),
        "product_code": payment.merchant_code,
        "signed_field_names": REQUEST_FIELDS,
        "success_url": settings.PUBLIC_BASE_URL
        + reverse("payments:esewa_success", args=[payment.transaction_uuid]),
        "failure_url": settings.PUBLIC_BASE_URL
        + reverse("payments:esewa_failure", args=[payment.transaction_uuid]),
    }
    fields["signature"] = signature(
        ",".join(f"{name}={fields[name]}" for name in REQUEST_FIELDS.split(","))
    )
    return fields


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate response field")
        result[name] = value
    return result


def decode_response(encoded, payment):
    try:
        if not encoded or len(encoded) > 8192:
            raise ValueError
        data = json.loads(
            base64.b64decode(encoded, validate=True),
            parse_float=Decimal,
            object_pairs_hook=_unique_object,
        )
        if (
            not isinstance(data, dict)
            or data.get("signed_field_names") != RESPONSE_FIELDS
        ):
            raise ValueError
        names = RESPONSE_FIELDS.split(",")
        if any(
            not isinstance(data[name], (str, int, Decimal))
            or isinstance(data[name], bool)
            for name in names
        ):
            raise ValueError
        expected = signature(",".join(f"{name}={data[name]}" for name in names))
        if not isinstance(data.get("signature"), str) or not hmac.compare_digest(
            expected, data["signature"]
        ):
            raise VerificationError("CALLBACK_SIGNATURE")
        if str(data["transaction_uuid"]) != str(payment.transaction_uuid):
            raise VerificationError("UUID_MISMATCH")
        if data["product_code"] != payment.merchant_code:
            raise VerificationError("MERCHANT_MISMATCH")
        if money(data["total_amount"]) != payment.amount:
            raise VerificationError("AMOUNT_MISMATCH")
        if (
            data["status"] != "COMPLETE"
            or not data["transaction_code"]
            or len(str(data["transaction_code"])) > 100
        ):
            raise ValueError
        return data
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
        raise VerificationError("CALLBACK_PAYLOAD")


def status_response(payment):
    # Never use callback-supplied URLs, IDs, prices or credentials for this call.
    started = monotonic()
    diagnostics = {}
    try:
        response = requests.get(
            settings.ESEWA_STATUS_URL,
            params={
                "product_code": payment.merchant_code,
                "total_amount": format(payment.amount, ".2f"),
                "transaction_uuid": str(payment.transaction_uuid),
            },
            timeout=10,
            allow_redirects=False,
        )
        diagnostics["http_status"] = response.status_code
        content_type = response.headers.get("Content-Type", "")
        diagnostics["response_format"] = (
            "json"
            if isinstance(content_type, str) and "json" in content_type.lower()
            else (
                "html"
                if isinstance(content_type, str) and "html" in content_type.lower()
                else "other"
            )
        )
        diagnostics["duration_ms"] = round((monotonic() - started) * 1000)
        if response.status_code != 200:
            code = (
                "HTTP_AUTH"
                if response.status_code in (401, 403)
                else (
                    "HTTP_NOT_FOUND"
                    if response.status_code == 404
                    else (
                        "HTTP_REDIRECT"
                        if 300 <= response.status_code < 400
                        else "HTTP_ERROR"
                    )
                )
            )
            raise VerificationError(code, diagnostics)
        response.raise_for_status()
        try:
            data = response.json(parse_float=Decimal, object_pairs_hook=_unique_object)
        except ValueError:
            raise VerificationError("INVALID_JSON", diagnostics)
        if not isinstance(data, dict):
            raise VerificationError("MALFORMED_RESPONSE", diagnostics)
        # Temporary in-memory metadata; never part of provider identity/signature validation.
        payment._verification_diagnostics = diagnostics
        return data
    except requests.RequestException as error:
        diagnostics["duration_ms"] = round((monotonic() - started) * 1000)
        raise VerificationError(network_error_code(error), diagnostics) from None


def validate_status(data, payment):
    if not isinstance(data, dict) or "status" not in data:
        if isinstance(data, dict) and ("code" in data or "error_message" in data):
            raise VerificationError(
                "PROVIDER_UNAVAILABLE" if data.get("code") == 0 else "PROVIDER_REJECTED"
            )
        raise VerificationError("MALFORMED_RESPONSE")
    # Official docs show both pid/scd/totalAmount/refId and the newer names.
    values = {}
    for key, alias in [
        ("transaction_uuid", "pid"),
        ("product_code", "scd"),
        ("total_amount", "totalAmount"),
        ("ref_id", "refId"),
    ]:
        if key in data and alias in data and str(data[key]) != str(data[alias]):
            raise VerificationError("MALFORMED_RESPONSE")
        values[key] = data.get(key, data.get(alias))
    if any(
        values[name] is None
        for name in ("transaction_uuid", "product_code", "total_amount")
    ):
        raise VerificationError("MALFORMED_RESPONSE")
    if str(values["transaction_uuid"]) != str(payment.transaction_uuid):
        raise VerificationError("UUID_MISMATCH")
    if values["product_code"] != payment.merchant_code:
        raise VerificationError("MERCHANT_MISMATCH")
    try:
        amount = money(values["total_amount"])
    except ValidationError:
        raise VerificationError("MALFORMED_RESPONSE")
    if amount != payment.amount:
        raise VerificationError("AMOUNT_MISMATCH")
    status = data["status"]
    if not isinstance(status, str):
        raise VerificationError("MALFORMED_RESPONSE")
    reference = values["ref_id"]
    if reference is not None and (
        not isinstance(reference, str) or len(reference) > 100
    ):
        raise VerificationError("MALFORMED_RESPONSE")
    if status in ("COMPLETE", "FULL_REFUND") and (
        not isinstance(reference, str) or not reference or len(reference) > 100
    ):
        raise VerificationError("MALFORMED_RESPONSE")
    return status, reference or ""
