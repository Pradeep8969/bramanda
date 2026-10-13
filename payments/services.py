import logging
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from orders.locking import lock_order
from orders.models import Order
from products.models import ProductVariant

from . import esewa
from .models import Payment, PaymentVerification

logger = logging.getLogger(__name__)


def record_error(payment_id, error, error_code, diagnostics=None, **details):
    diagnostics = diagnostics or {}
    PaymentVerification.objects.create(
        payment_id=payment_id,
        error=error,
        error_code=error_code,
        http_status=diagnostics.get("http_status"),
        response_format=diagnostics.get("response_format", ""),
        duration_ms=diagnostics.get("duration_ms"),
        **details
    )
    # Do not log URLs, query parameters, callback bodies, references, amounts or exceptions.
    logger.warning(
        "eSewa verification failed: payment_id=%s code=%s http_status=%s format=%s duration_ms=%s",
        payment_id,
        error_code,
        diagnostics.get("http_status"),
        diagnostics.get("response_format", ""),
        diagnostics.get("duration_ms"),
    )


def create_initial_payment(order):
    payment = Payment.objects.create(
        order=order,
        payment_method=order.payment_method,
        status="PENDING" if order.payment_method == "ESEWA" else "UNPAID",
        amount=order.grand_total,
        merchant_code=settings.ESEWA_PRODUCT_CODE,
    )
    if order.payment_method == "ESEWA":
        esewa.form_fields(
            payment
        )  # Configuration and amount validation inside checkout transaction.
    return payment


def change_stock_reservation(order, reserve):
    quantities = Counter()
    for item in order.items.select_for_update().order_by("variant_id"):
        if item.variant_id is None:
            raise ValidationError(
                "An order variant no longer exists; staff reconciliation is required."
            )
        quantities[item.variant_id] += item.quantity
    net = Counter()
    for record in InventoryTransaction.objects.select_for_update().filter(
        reference=order.order_number, transaction_type__in=["ORDER", "RETURN"]
    ):
        if (
            record.transaction_type == "ORDER"
            and record.quantity >= 0
            or record.transaction_type == "RETURN"
            and record.quantity <= 0
        ):
            raise ValidationError("Inconsistent order inventory history.")
        net[record.variant_id] -= record.quantity
    expected = Counter() if order.payment_stock_released else quantities
    if net != expected or not quantities:
        raise ValidationError(
            "Order inventory history does not reconcile; no stock was changed."
        )
    variants = {
        v.pk: v
        for v in ProductVariant.objects.select_for_update()
        .filter(pk__in=quantities)
        .order_by("pk")
    }
    if len(variants) != len(quantities):
        raise ValidationError("Missing order inventory variant.")
    for pk, quantity in sorted(quantities.items()):
        variant = variants[pk]
        if reserve and not all(
            (
                variant.is_active,
                variant.product.is_active,
                variant.product.category.is_active,
                variant.size.is_active,
                variant.color.is_active,
            )
        ):
            raise ValidationError("An order item is no longer available.")
        adjust_stock(
            variant,
            -quantity if reserve else quantity,
            "ORDER" if reserve else "RETURN",
            user=order.customer,
            reference=order.order_number,
            note=(
                "eSewa retry reservation"
                if reserve
                else "Verified failed/cancelled eSewa payment"
            ),
        )
    order.payment_stock_released = not reserve


@transaction.atomic
def retry_esewa(order_id):
    order = lock_order(order_id)
    if not order.can_retry_payment:
        raise ValidationError(
            "This order is not eligible for a new payment attempt. Re-check pending payments instead."
        )
    if order.payments.filter(status__in=["PENDING", "PAID"]).exists():
        raise ValidationError("An active payment already exists.")
    change_stock_reservation(order, reserve=True)
    order.payment_status = "PENDING"
    order.order_status = Order.OrderStatus.PENDING
    order.save(
        update_fields=[
            "payment_stock_released",
            "payment_status",
            "order_status",
            "updated_at",
        ]
    )
    return create_initial_payment(order)


class VerificationBusy(ValidationError):
    pass


def verify_payment(payment_id, callback=None):
    # Conditional write also serializes competing requests on local SQLite.
    started = timezone.now()
    claimed = (
        Payment.objects.filter(pk=payment_id)
        .filter(
            Q(verification_started_at__isnull=True)
            | Q(verification_started_at__lt=started - timedelta(seconds=60))
        )
        .update(verification_started_at=started)
    )
    if not claimed:
        raise VerificationBusy(
            "A payment check is already running. Please try again shortly."
        )
    error, error_code, diagnostics, provider_status, reference = "", "", {}, "", ""
    try:
        payment = Payment.objects.select_related("order").get(pk=payment_id)
        data = esewa.status_response(payment)
        diagnostics = getattr(payment, "_verification_diagnostics", {})
        provider_status, reference = esewa.validate_status(data, payment)
        if (
            callback
            and provider_status == "COMPLETE"
            and reference != str(callback["transaction_code"])
        ):
            raise esewa.VerificationError("REFERENCE_MISMATCH")
        known = {
            "COMPLETE",
            "PENDING",
            "FAILED",
            "CANCELED",
            "CANCELLED",
            "NOT_FOUND",
            "FULL_REFUND",
            "PARTIAL_REFUND",
            "AMBIGUOUS",
            "AMBIGIOUS",
        }
        if provider_status not in known:
            raise esewa.VerificationError("UNKNOWN_STATUS")
        with transaction.atomic():
            lock_order(payment.order_id)
            # A timed-out worker cannot reconcile after another check reclaimed its lease.
            if not Payment.objects.filter(
                pk=payment_id, verification_started_at=started
            ).update(verification_started_at=started):
                raise VerificationBusy(
                    "A newer payment check is running. Please check again shortly."
                )
            payment = apply_verified_status(payment_id, provider_status, reference)
            checked = timezone.now()
            Payment.objects.filter(pk=payment_id).update(
                last_verified_at=checked,
                last_checked_at=checked,
                provider_status=provider_status[:30],
                verification_error=error,
            )
            PaymentVerification.objects.create(
                payment_id=payment_id,
                provider_status=provider_status[:30],
                reference=reference,
                http_status=diagnostics.get("http_status"),
                response_format=diagnostics.get("response_format", ""),
                duration_ms=diagnostics.get("duration_ms"),
            )
            payment.last_verified_at = payment.last_checked_at = checked
            payment.verification_error = ""
            if provider_status == "COMPLETE":
                from orders.emails import queue_confirmation

                queue_confirmation(payment.order)
        return payment
    except VerificationBusy:
        raise
    except esewa.VerificationError as exc:
        error, error_code = "; ".join(exc.messages), exc.error_code
        diagnostics = exc.diagnostics or diagnostics
        payment.verification_error = error
        if error_code in {
            "UUID_MISMATCH",
            "MERCHANT_MISMATCH",
            "AMOUNT_MISMATCH",
            "REFERENCE_MISMATCH",
            "MALFORMED_RESPONSE",
        }:
            raise
        return payment
    except ValidationError:
        error_code = "RECONCILIATION_ERROR"
        error = "Payment reconciliation could not be completed safely. Please contact BRAMANDA; do not pay again."
        raise
    except DatabaseError:
        error_code = "DATABASE_ERROR"
        error = "Payment reconciliation was interrupted by a database conflict. Please try checking again."
        raise
    finally:
        with transaction.atomic():
            released = Payment.objects.filter(
                pk=payment_id, verification_started_at=started
            ).update(
                verification_started_at=None,
                **(
                    {"verification_error": error, "last_checked_at": timezone.now()}
                    if error
                    else {}
                )
            )
            if error and released:
                record_error(
                    payment_id,
                    error,
                    error_code,
                    diagnostics,
                    provider_status=provider_status[:30],
                    reference=reference,
                )


@transaction.atomic
def apply_verified_status(payment_id, provider_status, reference):
    order_id = Payment.objects.values_list("order_id", flat=True).get(pk=payment_id)
    # Every path locks Order before Payment; retries/callbacks serialize together.
    order = lock_order(order_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.amount != order.grand_total or payment.payment_method != "ESEWA":
        raise ValidationError("Payment and order do not match.")
    other_paid = order.payments.exclude(pk=payment.pk).filter(status="PAID").exists()
    if (
        provider_status in ("COMPLETE", "PARTIAL_REFUND", "FULL_REFUND")
        and payment.provider_reference
        and reference != payment.provider_reference
    ):
        raise esewa.VerificationError("REFERENCE_MISMATCH")
    if provider_status in ("PARTIAL_REFUND", "FULL_REFUND"):
        payment.review_required = True
    if payment.status == "PAID" and provider_status == "FULL_REFUND":
        payment.status = "REFUNDED"
        if not other_paid:
            order.payment_status = "REFUNDED"
    elif (
        provider_status == "COMPLETE"
        and payment.status != "PAID"
        and payment.status != "REFUNDED"
    ):
        # A saved provider form can complete after a failure/retry. Record real
        # funds even then, without a second stock debit. Extra paid attempts
        # remain visible for staff reconciliation rather than being discarded.
        payment.review_required = other_paid
        if order.payment_stock_released and not other_paid and not order.cancelled_at:
            try:
                with transaction.atomic():
                    change_stock_reservation(order, reserve=True)
            except ValidationError:
                payment.review_required = True
        payment.status = "PAID"
        order.payment_status = "PAID"
        payment.transaction_code = payment.provider_reference = reference
        payment.paid_at = timezone.now()
        if order.order_status == "PENDING" and not order.payment_stock_released:
            order.order_status = "CONFIRMED"
        elif order.payment_stock_released:
            order.order_status = "CANCELLED"
            payment.review_required = True
        if order.order_status == "CANCELLED":
            payment.review_required = True
        if order.cancelled_at:
            from orders.models import OrderEvent

            OrderEvent.objects.create(
                order=order,
                action="LATE_PAYMENT_RECONCILIATION",
                note="Verified payment recorded on cancelled order; separate financial review required.",
            )
    elif payment.status != "PENDING":
        payment.save(update_fields=["review_required"])
        return payment  # Duplicate/old failures never overwrite a newer attempt.
    elif provider_status in ("FAILED", "CANCELED", "CANCELLED", "NOT_FOUND"):
        payment.status = (
            "FAILED" if provider_status in ("FAILED", "NOT_FOUND") else "CANCELLED"
        )
        if not other_paid:
            order.payment_status = payment.status
            if not order.payment_stock_released:
                change_stock_reservation(order, reserve=False)
            order.order_status = "CANCELLED"
    else:
        payment.save(update_fields=["review_required"])
        return payment  # PENDING, ambiguous, partial refund and unknown responses are never treated as paid.
    payment.save(
        update_fields=[
            "status",
            "transaction_code",
            "provider_reference",
            "paid_at",
            "review_required",
            "updated_at",
        ]
    )
    order.save(
        update_fields=[
            "payment_status",
            "order_status",
            "payment_stock_released",
            "updated_at",
        ]
    )
    return payment


@transaction.atomic
def set_cod_payment_status(order_id, status):
    """Collect or correct COD cash without touching gateway payments or stock."""
    order = lock_order(order_id)
    if status not in ("UNPAID", "PAID"):
        raise ValidationError("Choose Paid or Payment Remaining.")
    if order.order_status == "CANCELLED" or order.cancelled_at:
        raise ValidationError(
            "Payment status cannot be changed for a cancelled COD order."
        )
    if order.payment_method != "COD" or order.payment_status not in (
        "UNPAID",
        "PENDING",
        "PAID",
    ):
        raise ValidationError("Only outstanding COD payments can be collected.")
    payments = list(order.payments.select_for_update().order_by("pk"))
    if len(payments) > 1:
        raise ValidationError("Multiple COD payment records require financial review.")
    payment = payments[0] if payments else None
    if payment is None:
        payment = Payment.objects.create(
            order=order,
            payment_method="COD",
            status=order.payment_status,
            amount=order.grand_total,
        )
    if (
        payment.payment_method != "COD"
        or payment.amount != order.grand_total
        or payment.status not in ("UNPAID", "PENDING", "PAID")
        or payment.provider_reference
        or payment.transaction_code
        or payment.review_required
    ):
        raise ValidationError("COD payment and order do not match.")
    if payment.status != status:
        payment.status = status
        payment.paid_at = timezone.now() if status == "PAID" else None
        payment.save(update_fields=["status", "paid_at", "updated_at"])
    order.payment_status = status
    order.save(update_fields=["payment_status", "updated_at"])
    return payment


def collect_cod(order_id):
    # Preserve the existing service API for other COD collection callers.
    return set_cod_payment_status(order_id, "PAID")
