from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from orders.models import Order
from products.models import ProductVariant
from . import esewa
from .models import Payment


def create_initial_payment(order):
    payment = Payment.objects.create(order=order, payment_method=order.payment_method,
        status='PENDING' if order.payment_method == 'ESEWA' else 'UNPAID', amount=order.grand_total)
    if order.payment_method == 'ESEWA':
        esewa.form_fields(payment)  # Configuration and amount validation inside checkout transaction.
    return payment


def change_stock_reservation(order, reserve):
    quantities = Counter()
    for item in order.items.select_for_update().order_by('variant_id'):
        if item.variant_id is None:
            raise ValidationError('An order variant no longer exists; staff reconciliation is required.')
        quantities[item.variant_id] += item.quantity
    net = Counter()
    for record in InventoryTransaction.objects.select_for_update().filter(
            reference=order.order_number, transaction_type__in=['ORDER', 'RETURN']):
        if (record.transaction_type == 'ORDER' and record.quantity >= 0
                or record.transaction_type == 'RETURN' and record.quantity <= 0):
            raise ValidationError('Inconsistent order inventory history.')
        net[record.variant_id] -= record.quantity
    expected = Counter() if order.payment_stock_released else quantities
    if net != expected or not quantities:
        raise ValidationError('Order inventory history does not reconcile; no stock was changed.')
    variants = {v.pk: v for v in ProductVariant.objects.select_for_update().filter(pk__in=quantities).order_by('pk')}
    if len(variants) != len(quantities):
        raise ValidationError('Missing order inventory variant.')
    for pk, quantity in sorted(quantities.items()):
        variant = variants[pk]
        if reserve and not all((variant.is_active, variant.product.is_active,
                               variant.product.category.is_active, variant.size.is_active, variant.color.is_active)):
            raise ValidationError('An order item is no longer available.')
        adjust_stock(variant, -quantity if reserve else quantity, 'ORDER' if reserve else 'RETURN',
                     user=order.customer, reference=order.order_number,
                     note='eSewa retry reservation' if reserve else 'Verified failed/cancelled eSewa payment')
    order.payment_stock_released = not reserve


@transaction.atomic
def retry_esewa(order_id):
    order = Order.objects.select_for_update().get(pk=order_id)
    if not order.can_retry_payment:
        raise ValidationError('This order is not eligible for a new payment attempt. Re-check pending payments instead.')
    if order.payments.filter(status__in=['PENDING', 'PAID']).exists():
        raise ValidationError('An active payment already exists.')
    change_stock_reservation(order, reserve=True)
    order.payment_status = 'PENDING'
    order.order_status = Order.OrderStatus.PENDING
    order.save(update_fields=['payment_stock_released', 'payment_status', 'order_status', 'updated_at'])
    return create_initial_payment(order)


def verify_payment(payment_id, callback=None):
    payment = Payment.objects.select_related('order').get(pk=payment_id)
    result = esewa.validate_status(esewa.status_response(payment), payment)
    if result is None:
        return payment
    provider_status, reference = result
    if callback and provider_status == 'COMPLETE' and reference != str(callback['transaction_code']):
        raise ValidationError('Callback and verified transaction references do not match.')
    return apply_verified_status(payment_id, provider_status, reference)


@transaction.atomic
def apply_verified_status(payment_id, provider_status, reference):
    order_id = Payment.objects.values_list('order_id', flat=True).get(pk=payment_id)
    # Every path locks Order before Payment; retries/callbacks serialize together.
    order = Order.objects.select_for_update().get(pk=order_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    if payment.amount != order.grand_total or payment.payment_method != 'ESEWA':
        raise ValidationError('Payment and order do not match.')
    other_paid = order.payments.exclude(pk=payment.pk).filter(status='PAID').exists()
    if payment.status == 'PAID' and provider_status == 'FULL_REFUND':
        payment.status = 'REFUNDED'
        if not other_paid:
            order.payment_status = 'REFUNDED'
    elif provider_status == 'COMPLETE' and payment.status != 'PAID' and payment.status != 'REFUNDED':
        # A saved provider form can complete after a failure/retry. Record real
        # funds even then, without a second stock debit. Extra paid attempts
        # remain visible for staff reconciliation rather than being discarded.
        payment.review_required = other_paid
        if order.payment_stock_released and not other_paid:
            try:
                with transaction.atomic():
                    change_stock_reservation(order, reserve=True)
            except ValidationError:
                payment.review_required = True
        payment.status = 'PAID'
        order.payment_status = 'PAID'
        payment.transaction_code = payment.provider_reference = reference
        payment.paid_at = timezone.now()
        if order.order_status == 'PENDING' and not order.payment_stock_released:
            order.order_status = 'CONFIRMED'
        elif order.payment_stock_released:
            order.order_status = 'CANCELLED'
            payment.review_required = True
        if order.order_status == 'CANCELLED':
            payment.review_required = True
    elif payment.status != 'PENDING':
        return payment  # Duplicate/old failures never overwrite a newer attempt.
    elif provider_status in ('FAILED', 'CANCELED', 'CANCELLED', 'NOT_FOUND'):
        payment.status = 'FAILED' if provider_status in ('FAILED', 'NOT_FOUND') else 'CANCELLED'
        if not other_paid:
            order.payment_status = payment.status
            if not order.payment_stock_released:
                change_stock_reservation(order, reserve=False)
            order.order_status = 'CANCELLED'
    else:
        return payment  # PENDING, ambiguous, partial refund and unknown responses are never treated as paid.
    payment.save(update_fields=['status', 'transaction_code', 'provider_reference', 'paid_at', 'review_required', 'updated_at'])
    order.save(update_fields=['payment_status', 'order_status', 'payment_stock_released', 'updated_at'])
    return payment


@transaction.atomic
def collect_cod(order_id):
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.payment_method != 'COD' or order.payment_status not in ('UNPAID', 'PENDING', 'PAID'):
        raise ValidationError('Only outstanding COD payments can be collected.')
    payment = order.payments.select_for_update().first()
    if payment is None:
        payment = Payment.objects.create(order=order, payment_method='COD', status=order.payment_status,
                                         amount=order.grand_total)
    if payment.payment_method != 'COD' or payment.amount != order.grand_total:
        raise ValidationError('COD payment and order do not match.')
    if payment.status != 'PAID':
        payment.status = 'PAID'
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at', 'updated_at'])
    order.payment_status = 'PAID'
    order.save(update_fields=['payment_status', 'updated_at'])
    return payment
