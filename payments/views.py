from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe

from orders.models import Order
from . import esewa
from .models import Payment
from .services import retry_esewa, verify_payment


def accessible_orders(request):
    if request.user.is_active and request.user.role in ('OWNER', 'STAFF'):
        return Order.objects.all()
    return Order.objects.filter(customer=request.user)


def customer_payment(request, transaction_uuid):
    return get_object_or_404(Payment.objects.select_related('order').filter(order__customer=request.user),
                             transaction_uuid=transaction_uuid, payment_method='ESEWA')


@login_required
@require_safe
def invoice(request, order_number):
    order = get_object_or_404(accessible_orders(request).prefetch_related('items'), order_number=order_number)
    return render(request, 'payments/document.html', {'order': order, 'is_receipt': False})


@login_required
@require_safe
def receipt(request, order_number):
    order = get_object_or_404(accessible_orders(request).prefetch_related('items'), order_number=order_number,
                              payment_status='PAID')
    payment = order.payments.filter(status='PAID').order_by('paid_at', 'pk').first()
    if payment is None:
        raise Http404
    return render(request, 'payments/document.html', {'order': order, 'payment': payment, 'is_receipt': True})


@login_required
@require_safe
def pay(request, transaction_uuid):
    payment = customer_payment(request, transaction_uuid)
    if payment.status != 'PENDING' or payment.order.payment_status != 'PENDING' or payment.order.payment_stock_released:
        return redirect('payments:result', transaction_uuid=transaction_uuid)
    try:
        fields = esewa.form_fields(payment)
    except ValidationError as error:
        return render(request, 'payments/error.html', {'error': '; '.join(error.messages)}, status=400)
    return render(request, 'payments/pay.html', {'payment': payment, 'fields': fields,
                                               'payment_url': settings.ESEWA_PAYMENT_URL})


@require_safe
def esewa_success(request, transaction_uuid):
    # Signed callbacks work even when a session cookie does not survive the provider redirect.
    payment = get_object_or_404(Payment.objects.select_related('order'), transaction_uuid=transaction_uuid,
                                payment_method='ESEWA')
    try:
        callback = esewa.decode_response(request.GET.get('data'), payment)
        verify_payment(payment.pk, callback=callback)
    except (ValidationError, DatabaseError) as error:
        explanation = '; '.join(error.messages) if isinstance(error, ValidationError) else 'Payment changed concurrently. Re-check its status.'
        return render(request, 'payments/error.html', {'error': explanation}, status=400)
    return redirect('payments:result', transaction_uuid=transaction_uuid)


@require_safe
def esewa_failure(request, transaction_uuid):
    payment = get_object_or_404(Payment, transaction_uuid=transaction_uuid, payment_method='ESEWA')
    try:
        # An unsigned failure redirect itself is not proof of failure/cancellation.
        verify_payment(payment.pk)
    except (ValidationError, DatabaseError):
        return render(request, 'payments/error.html', {'error': 'Unable to reconcile payment. Re-check its status or contact staff.'}, status=400)
    return redirect('payments:result', transaction_uuid=transaction_uuid)


@login_required
@require_POST
def recheck(request, transaction_uuid):
    payment = get_object_or_404(Payment.objects.select_related('order').filter(order__in=accessible_orders(request)),
                                transaction_uuid=transaction_uuid, payment_method='ESEWA')
    try:
        verify_payment(payment.pk)
    except (ValidationError, DatabaseError):
        messages.error(request, 'Unable to reconcile payment. No unverified payment was accepted; please contact staff.')
    if payment.order.customer_id != request.user.pk and request.user.role in ('OWNER', 'STAFF'):
        namespace = 'owner' if request.user.role == 'OWNER' else 'dashboard'
        return redirect(f'{namespace}:order_detail', order_number=payment.order.order_number)
    return redirect('payments:result', transaction_uuid=transaction_uuid)


@login_required
@require_POST
def retry(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, customer=request.user, payment_method='ESEWA')
    try:
        payment = retry_esewa(order.pk)
    except (ValidationError, DatabaseError) as error:
        message = '; '.join(error.messages) if isinstance(error, ValidationError) else 'Stock changed. Please retry.'
        messages.error(request, message)
        return redirect('orders:detail', order_number=order_number)
    return redirect('payments:pay', transaction_uuid=payment.transaction_uuid)


@login_required
@require_safe
def result(request, transaction_uuid):
    payment = customer_payment(request, transaction_uuid)
    return render(request, 'payments/result.html', {'order': payment.order, 'payment': payment})
