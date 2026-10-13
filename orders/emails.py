"""EmailJS order confirmations. Never log provider bodies, exceptions or credentials."""

import logging

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html_join
from django.views.decorators.debug import sensitive_variables

from payments.invoice_links import invoice_url, validate_invoice_url

from .models import Order, OrderConfirmationEmail

logger = logging.getLogger(__name__)
ENDPOINT = "https://api.emailjs.com/api/v1.0/email/send"


def provider_error_code(response):
    # Persist only recognized categories, never arbitrary provider text (PII/secrets).
    if response.status_code == 403 and isinstance(response.text, str):
        body = response.text.lower()
        if "non-browser" in body and ("disabled" in body or "disable" in body):
            return "SERVER_API_DISABLED"
    return f"HTTP_{response.status_code}"


def eligible(order):
    if order.cancelled_at or order.order_status in ("PENDING", "CANCELLED"):
        return False
    if order.payment_method == "COD":
        return True
    return (
        order.payment_status == "PAID"
        and not order.payment_stock_released
        and order.payments.filter(
            payment_method="ESEWA",
            status="PAID",
            provider_status="COMPLETE",
            last_verified_at__isnull=False,
            verification_error="",
            review_required=False,
            amount=order.grand_total,
        )
        .exclude(provider_reference="")
        .exists()
    )


def queue_confirmation(order):
    try:
        # A mail persistence failure rolls back only this savepoint, not checkout.
        with transaction.atomic():
            if not eligible(order):
                return
            delivery, _ = OrderConfirmationEmail.objects.get_or_create(order=order)
            transaction.on_commit(lambda: send_confirmation(delivery.pk), robust=True)
    except Exception:
        logger.warning(
            "Order email queue failed: order_id=%s code=QUEUE_FAILED", order.pk
        )


def template_params(order):
    # Use purchased snapshots, never the customer's current profile or catalogue prices.
    items = [
        dict(
            name=item.product_name,
            product_name=item.product_name,
            quantity=item.quantity,
            price=f"{item.unit_price:.2f}",
            unit_price=f"{item.unit_price:.2f}",
            total=f"{item.subtotal:.2f}",
            size=item.size_name,
            color=item.color_name,
            sku=item.sku,
        )
        for item in order.items.order_by("pk")
    ]
    products = "\n".join(
        f"{i['name']} ({i['color']} / {i['size']}) x {i['quantity']}"
        f" @ Rs. {i['price']} = Rs. {i['total']}"
        for i in items
    )
    # EmailJS order-table contract; preserve the existing items/quantity aliases.
    orders = [
        dict(name=i["name"], units=i["quantity"], price=i["price"], total=i["total"])
        for i in items
    ]
    payment = order.payments.filter(status="PAID").order_by("paid_at", "pk").first()
    name = f"{order.first_name} {order.last_name}".strip()
    params = dict(
        to_email=order.email,
        email=order.email,
        customer_email=order.email,
        to_name=name,
        name=name,
        customer_name=name,
        first_name=order.first_name,
        last_name=order.last_name,
        phone_number=order.phone_number,
        order_number=order.order_number,
        order_id=order.order_number,
        order_date=order.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        products=products,
        order_items=products,
        items=items,
        orders=orders,
        products_html=str(
            format_html_join(
                "",
                "<p>{} / {} / {} × {} — Rs. {}</p>",
                (
                    (i["name"], i["color"], i["size"], i["quantity"], i["total"])
                    for i in items
                ),
            )
        ),
        subtotal=f"{order.subtotal:.2f}",
        shipping_cost=f"{order.shipping_cost:.2f}",
        shipping=f"{order.shipping_cost:.2f}",
        grand_total=f"{order.grand_total:.2f}",
        total=f"{order.grand_total:.2f}",
        currency="NPR",
        payment_method=order.get_payment_method_display(),
        payment_status=order.get_payment_status_display(),
        amount_paid=f"{payment.amount:.2f}" if payment else "0.00",
        amount_due="0.00" if payment else f"{order.grand_total:.2f}",
        transaction_code=payment.transaction_code if payment else "",
        payment_reference=payment.provider_reference if payment else "",
        paid_at=payment.paid_at.isoformat() if payment and payment.paid_at else "",
        shipping_address=order.shipping_address,
        delivery_address=order.shipping_address,
        address=order.shipping_address,
        invoice_url=invoice_url(order),
    )
    params["invoice_filename"] = f"{order.order_number}.pdf"
    for target, source in settings.EMAILJS_TEMPLATE_VARIABLES.items():
        params[target] = params[source]
    validate_invoice_url(params.get("invoice_url"), order)
    return params


@sensitive_variables("keys", "params", "response")
def send_confirmation(delivery_id):
    """Persist a claim before HTTP. Never retry uncertain acceptance automatically."""
    claimed = False
    try:
        delivery = OrderConfirmationEmail.objects.select_related("order").get(
            pk=delivery_id
        )
        if delivery.status != "PENDING" or not eligible(delivery.order):
            return
        keys = [
            settings.EMAILJS_SERVICE_ID,
            settings.EMAILJS_ORDER_TEMPLATE_ID,
            settings.EMAILJS_PUBLIC_KEY,
            settings.EMAILJS_PRIVATE_KEY,
        ]
        if not all(keys):
            OrderConfirmationEmail.objects.filter(
                pk=delivery_id, status="PENDING"
            ).update(error_code="CONFIGURATION_MISSING")
            return
        params = template_params(delivery.order)
        validate_invoice_url(params.get("invoice_url"), delivery.order)
        claimed = bool(
            OrderConfirmationEmail.objects.filter(
                pk=delivery_id, status="PENDING"
            ).update(status="SENDING", attempted_at=timezone.now(), error_code="")
        )
        if not claimed:
            return
        response = requests.post(
            ENDPOINT,
            json=dict(
                service_id=keys[0],
                template_id=keys[1],
                user_id=keys[2],
                accessToken=keys[3],
                template_params=params,
            ),
            timeout=(3.05, 10),
            allow_redirects=False,
        )
        if response.status_code == 200:
            OrderConfirmationEmail.objects.filter(pk=delivery_id).update(
                status="SENT", sent_at=timezone.now(), error_code=""
            )
        else:
            error_code = provider_error_code(response)
            OrderConfirmationEmail.objects.filter(pk=delivery_id).update(
                status="FAILED", error_code=error_code
            )
            logger.warning(
                "Order email failed: delivery_id=%s code=%s", delivery_id, error_code
            )
    except Exception:
        # Timeouts may follow provider acceptance; resending could duplicate mail.
        try:
            OrderConfirmationEmail.objects.filter(pk=delivery_id).update(
                status="UNKNOWN" if claimed else "PENDING",
                error_code="DELIVERY_UNCERTAIN" if claimed else "PREPARATION_FAILED",
            )
        except Exception:
            pass
        logger.warning(
            "Order email failed: delivery_id=%s code=%s",
            delivery_id,
            "DELIVERY_UNCERTAIN" if claimed else "PREPARATION_FAILED",
        )
