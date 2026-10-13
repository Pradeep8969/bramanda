from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from orders.models import Order

from . import esewa
from .invoice_links import invoice_identity
from .models import Payment
from .services import VerificationBusy, record_error, retry_esewa, verify_payment


def verified_confirmation_url(payment):
    order = payment.order
    if (
        payment.status == "PAID"
        and order.payment_status == "PAID"
        and payment.provider_status == "COMPLETE"
        and payment.last_verified_at
        and not payment.verification_error
        and not payment.review_required
        and order.order_status not in ("PENDING", "CANCELLED")
        and not order.payment_stock_released
    ):
        return reverse("orders:detail", args=[order.order_number])
    return ""


def notify_payment_success(request, payment, previous_status):
    if (
        previous_status != "PAID"
        and verified_confirmation_url(payment)
        and request.user.is_authenticated
        and request.user.pk == payment.order.customer_id
        and not getattr(request, "_payment_success_notified", False)
    ):
        messages.success(
            request,
            "Your eSewa sandbox payment is verified. Your order is confirmed; delivery awaits staff processing.",
        )
        request._payment_success_notified = True


def after_verification(request, payment, previous_status):
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    url = verified_confirmation_url(payment)
    if url:
        notify_payment_success(request, payment, previous_status)
        return redirect(url)
    return redirect("payments:result", transaction_uuid=payment.transaction_uuid)


def accessible_orders(request):
    if request.user.is_active and request.user.role in ("OWNER", "STAFF"):
        return Order.objects.all()
    return Order.objects.filter(customer=request.user)


def customer_payment(request, transaction_uuid):
    return get_object_or_404(
        Payment.objects.select_related("order").filter(order__customer=request.user),
        transaction_uuid=transaction_uuid,
        payment_method="ESEWA",
    )


@login_required
@require_safe
def invoice(request, order_number):
    order = get_object_or_404(
        accessible_orders(request).prefetch_related("items"), order_number=order_number
    )
    return render(
        request, "payments/document.html", {"order": order, "is_receipt": False}
    )


@never_cache
@require_safe
def signed_invoice(request, token):
    # Possession of a valid bearer link grants access to this invoice only.
    try:
        identity = invoice_identity(token)
    except (signing.BadSignature, ValueError, TypeError, ImproperlyConfigured):
        raise Http404("This invoice link is invalid or has expired.") from None
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items"),
        pk=identity["order"],
        customer_id=identity["customer"],
        order_number=identity["number"],
    )
    response = render(
        request, "payments/document.html", {"order": order, "is_receipt": False}
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@require_safe
def receipt(request, order_number):
    order = get_object_or_404(
        accessible_orders(request).prefetch_related("items"),
        order_number=order_number,
        payment_status="PAID",
    )
    payment = order.payments.filter(status="PAID").order_by("paid_at", "pk").first()
    if payment is None:
        raise Http404
    return render(
        request,
        "payments/document.html",
        {"order": order, "payment": payment, "is_receipt": True},
    )


@login_required
@require_safe
def pay(request, transaction_uuid):
    payment = customer_payment(request, transaction_uuid)
    if (
        payment.status != "PENDING"
        or payment.order.payment_status != "PENDING"
        or payment.order.payment_stock_released
        or payment.order.order_status == "CANCELLED"
    ):
        return redirect("payments:result", transaction_uuid=transaction_uuid)
    try:
        fields = esewa.form_fields(payment)
    except ValidationError as error:
        return render(
            request,
            "payments/error.html",
            {"error": "; ".join(error.messages)},
            status=400,
        )
    return render(
        request,
        "payments/pay.html",
        {
            "payment": payment,
            "fields": fields,
            "payment_url": settings.ESEWA_PAYMENT_URL,
        },
    )


@require_safe
def esewa_success(request, transaction_uuid):
    # Signed callbacks work even when a session cookie does not survive the provider redirect.
    payment = get_object_or_404(
        Payment.objects.select_related("order"),
        transaction_uuid=transaction_uuid,
        payment_method="ESEWA",
    )
    callback_validated = False
    previous_status = payment.status
    try:
        encoded = request.GET.get("data")
        callback = (
            esewa.decode_response(encoded, payment) if encoded is not None else None
        )
        callback_validated = True
        verify_payment(payment.pk, callback=callback)
    except (ValidationError, DatabaseError) as error:
        explanation = (
            "; ".join(error.messages)
            if isinstance(error, ValidationError)
            else "Payment changed concurrently. Re-check its status."
        )
        if isinstance(error, esewa.VerificationError) and not callback_validated:
            Payment.objects.filter(
                pk=payment.pk, verification_started_at__isnull=True
            ).update(last_checked_at=timezone.now(), verification_error=explanation)
            record_error(payment.pk, explanation, error.error_code)
        if (
            request.user.is_authenticated
            and payment.order.customer_id == request.user.pk
        ):
            payment.refresh_from_db()
            display = payment_display(payment)
            display.update(
                title="Verification unavailable",
                description=explanation,
                state="error",
                symbol="!",
            )
            return render(
                request,
                "payments/result.html",
                {"order": payment.order, "payment": payment, "display": display},
                status=400,
            )
        return render(
            request, "payments/error.html", {"error": explanation}, status=400
        )
    return after_verification(request, payment, previous_status)


@require_safe
def esewa_failure(request, transaction_uuid):
    payment = get_object_or_404(
        Payment, transaction_uuid=transaction_uuid, payment_method="ESEWA"
    )
    previous_status = payment.status
    try:
        # An unsigned failure redirect itself is not proof of failure/cancellation.
        verify_payment(payment.pk)
    except (ValidationError, DatabaseError) as error:
        explanation = (
            "; ".join(error.messages)
            if isinstance(error, ValidationError)
            else "Payment changed concurrently. Re-check its status."
        )
        if (
            request.user.is_authenticated
            and payment.order.customer_id == request.user.pk
        ):
            payment.refresh_from_db()
            display = payment_display(payment)
            display.update(
                title="Verification unavailable",
                description=explanation,
                state="error",
                symbol="!",
            )
            return render(
                request,
                "payments/result.html",
                {"order": payment.order, "payment": payment, "display": display},
                status=400,
            )
        return render(
            request, "payments/error.html", {"error": explanation}, status=400
        )
    return after_verification(request, payment, previous_status)


@login_required
@require_POST
def recheck(request, transaction_uuid):
    payment = get_object_or_404(
        Payment.objects.select_related("order").filter(
            order__in=accessible_orders(request)
        ),
        transaction_uuid=transaction_uuid,
        payment_method="ESEWA",
    )
    error = ""
    code = 200
    previous_status = payment.status
    try:
        verify_payment(payment.pk)
    except VerificationBusy as exc:
        error, code = "; ".join(exc.messages), 409
    except (ValidationError, DatabaseError):
        error, code = (
            "Unable to reconcile payment. Please try checking again or contact BRAMANDA.",
            503,
        )
    payment.refresh_from_db()
    payment.order.refresh_from_db()
    error = (
        payment.verification_error
        if code != 409 and payment.verification_error
        else error
    )
    if request.headers.get("Accept") == "application/json":
        payload = payment_display(payment)
        if payment.order.customer_id != request.user.pk:
            payload["confirmation_url"] = ""
        if not error and payload["confirmation_url"]:
            notify_payment_success(request, payment, previous_status)
        payload.update(
            ok=not bool(error),
            message=error or payload["description"],
            order_status=payment.order.get_order_status_display(),
        )
        return JsonResponse(
            payload, status=code if code != 200 else (503 if error else 200)
        )
    if error:
        messages.error(request, error)
    elif not (
        payment.order.customer_id == request.user.pk
        and verified_confirmation_url(payment)
    ):
        messages.info(request, payment_display(payment)["description"])
    if payment.order.customer_id != request.user.pk and request.user.role in (
        "OWNER",
        "STAFF",
    ):
        namespace = "owner" if request.user.role == "OWNER" else "dashboard"
        return redirect(
            f"{namespace}:order_detail", order_number=payment.order.order_number
        )
    return after_verification(request, payment, previous_status)


@login_required
@require_POST
def retry(request, order_number):
    order = get_object_or_404(
        Order, order_number=order_number, customer=request.user, payment_method="ESEWA"
    )
    try:
        payment = retry_esewa(order.pk)
    except (ValidationError, DatabaseError) as error:
        message = (
            "; ".join(error.messages)
            if isinstance(error, ValidationError)
            else "Stock changed. Please retry."
        )
        messages.error(request, message)
        return redirect("orders:detail", order_number=order_number)
    return redirect("payments:pay", transaction_uuid=payment.transaction_uuid)


@login_required
@require_safe
def result(request, transaction_uuid):
    payment = customer_payment(request, transaction_uuid)
    return render(
        request,
        "payments/result.html",
        {
            "order": payment.order,
            "payment": payment,
            "display": payment_display(payment),
        },
    )


def payment_display(payment):
    state = payment.status
    title, description = (
        "Awaiting verification",
        "Your payment is unresolved. Check its status before making another payment.",
    )
    if state == "PAID":
        title, description = (
            "Payment verified",
            "eSewa has confirmed your payment. Your order details are ready.",
        )
    elif state in ("FAILED", "CANCELLED"):
        title, description = (
            "Payment unsuccessful",
            "eSewa did not complete this attempt. You can start a new payment attempt.",
        )
    elif state == "REFUNDED":
        title, description = (
            "Payment refunded",
            "eSewa reports a full refund. Contact BRAMANDA about your order.",
        )
    if payment.provider_status in ("PARTIAL_REFUND", "AMBIGUOUS", "AMBIGIOUS"):
        description = "eSewa reports a payment requiring review. Contact BRAMANDA before paying again."
    if payment.verification_error:
        title, description = "Verification unavailable", payment.verification_error
    if payment.review_required:
        description += " This order requires staff review before fulfillment. Contact BRAMANDA with your order number."
    visual_state = (
        "success"
        if state == "PAID"
        else "failed" if state in ("FAILED", "CANCELLED", "REFUNDED") else "pending"
    )
    if payment.verification_error:
        visual_state = "error"
    order = payment.order
    return {
        "status": state,
        "title": title,
        "description": description,
        "state": visual_state,
        "symbol": {
            "success": "\u2713",
            "failed": "\u00d7",
            "pending": "\u25f7",
            "error": "!",
        }[visual_state],
        "provider_status": payment.provider_status,
        "reference": payment.provider_reference
        or payment.transaction_code
        or "Not available yet",
        "last_verified_at": (
            payment.last_verified_at.isoformat() if payment.last_verified_at else None
        ),
        "last_checked_at": (
            payment.last_checked_at.isoformat() if payment.last_checked_at else None
        ),
        "confirmation_url": verified_confirmation_url(payment),
        "receipt_url": (
            reverse("payments:receipt", args=[order.order_number])
            if order.payment_status == "PAID" and state == "PAID"
            else ""
        ),
        "retry_url": (
            reverse("payments:retry", args=[order.order_number])
            if order.can_retry_payment
            else ""
        ),
        "can_continue": state == "PENDING"
        and order.order_status != "CANCELLED"
        and not order.payment_stock_released
        and order.payment_status == "PENDING"
        and not payment.provider_status
        and not payment.verification_error,
    }
