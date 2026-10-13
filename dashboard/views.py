from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render as django_render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from inventory.models import InventoryTransaction
from inventory.services import StockConflict, adjust_stock, set_stock
from inventory.stock_levels import LOW_STOCK_MAX
from orders.locking import lock_order
from orders.models import Order
from payments.services import set_cod_payment_status
from products.models import ProductVariant

from .forms import (
    CODPaymentForm,
    DeliveryStatusForm,
    OrderStatusForm,
    StockAdjustmentForm,
    StockUpdateForm,
)
from .models import StaffActivity
from .permissions import staff_required


@staff_required
@require_safe
def home(request):
    counts = dict(Order.objects.values_list("order_status").annotate(total=Count("pk")))
    cards = [
        (label + " Orders", counts.get(value, 0))
        for value, label in Order.OrderStatus.choices
        if value != Order.OrderStatus.CANCELLED
    ]
    cards += [
        (
            "Orders Today",
            Order.objects.filter(created_at__date=timezone.localdate()).count(),
        ),
        (
            "Low Stock Variants",
            ProductVariant.objects.filter(
                is_active=True, stock_quantity__gte=1, stock_quantity__lte=LOW_STOCK_MAX
            ).count(),
        ),
    ]
    return render_dashboard(
        request,
        "dashboard/home.html",
        {"cards": cards, "orders": Order.objects.select_related("customer")[:10]},
    )


@staff_required
@require_safe
def order_list(request):
    orders = Order.objects.select_related("customer").all()
    query = request.GET.get("q", "").strip()
    if query:
        orders = orders.filter(
            Q(order_number__icontains=query)
            | Q(customer__username__icontains=query)
            | Q(customer__first_name__icontains=query)
            | Q(customer__last_name__icontains=query)
            | Q(customer__phone_number__icontains=query)
            | Q(phone_number__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    filters = []
    for field, choices in [
        ("order_status", Order.OrderStatus.choices),
        ("delivery_status", Order.DeliveryStatus.choices),
        ("payment_status", Order.PaymentStatus.choices),
    ]:
        value = request.GET.get(field, "")
        if value:
            orders = orders.filter(**{field: value})
        filters.append((field, field.replace("_", " ").title(), choices, value))
    return render_dashboard(
        request,
        "dashboard/orders.html",
        {"orders": orders, "q": query, "filters": filters},
    )


@staff_required
@require_safe
def order_detail(request, order_number):
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items"),
        order_number=order_number,
    )
    return render_dashboard(
        request,
        "dashboard/order_detail.html",
        {
            "order": order,
            "delivery_form": DeliveryStatusForm(
                initial={"delivery_status": order.delivery_status}
            ),
            "payment_status_label": (
                "Paid"
                if order.payment_status == Order.PaymentStatus.PAID
                else "Payment Remaining"
            ),
            "can_update_cod_payment": (
                order.payment_method == Order.PaymentMethod.COD
                and order.order_status != Order.OrderStatus.CANCELLED
                and order.cancelled_at is None
                and order.payment_status in ("UNPAID", "PENDING", "PAID")
            ),
            "payment_form": CODPaymentForm(
                initial={
                    "payment_status": (
                        "PAID"
                        if order.payment_status == Order.PaymentStatus.PAID
                        else "UNPAID"
                    )
                }
            ),
        },
    )


def update_status(request, order_number, field, form_class, action):
    try:
        return update_status_transaction(
            request, order_number, field, form_class, action
        )
    except DatabaseError:
        return render_dashboard(
            request,
            "dashboard/invalid.html",
            {"error": "The order changed during this update. Please reload and retry."},
            status=409,
        )


def update_status_transaction(request, order_number, field, form_class, action):
    form = form_class(request.POST)
    if not form.is_valid():
        return render_dashboard(
            request, "dashboard/invalid.html", {"form": form}, status=400
        )
    order_id = get_object_or_404(Order, order_number=order_number).pk
    with transaction.atomic():
        order = lock_order(order_id)
        if (
            field == "payment_status"
            and order.payment_method != Order.PaymentMethod.COD
        ):
            return render_dashboard(
                request,
                "dashboard/invalid.html",
                {"error": "Only COD payment status can be updated manually."},
                status=400,
            )
        old = getattr(order, field)
        new = form.cleaned_data[field]
        if order.order_status == "CANCELLED" and old != new:
            return render_dashboard(
                request,
                "dashboard/invalid.html",
                {"error": "Cancelled orders cannot enter fulfillment or collect COD."},
                status=400,
            )
        if field == "order_status" and new == "CANCELLED" and old != new:
            return render_dashboard(
                request,
                "dashboard/invalid.html",
                {"error": "Order cancellation is unavailable."},
                status=400,
            )
        stages = {
            "order_status": [
                "PENDING",
                "CONFIRMED",
                "PROCESSING",
                "PACKED",
                "SHIPPED",
                "DELIVERED",
            ],
            "delivery_status": [
                "PENDING",
                "PROCESSING",
                "PACKED",
                "SHIPPED",
                "OUT_FOR_DELIVERY",
                "DELIVERED",
            ],
        }
        if (
            field in stages
            and old in stages[field]
            and new in stages[field]
            and stages[field].index(new) < stages[field].index(old)
        ):
            return render_dashboard(
                request,
                "dashboard/invalid.html",
                {"error": "Fulfillment progress cannot move backwards."},
                status=400,
            )
        if (
            order.payment_method == "ESEWA"
            and (order.payment_status != "PAID" or order.payment_stock_released)
            and (
                (field == "order_status" and new not in ("PENDING", "CANCELLED"))
                or (field == "delivery_status" and new != "PENDING")
            )
        ):
            return render_dashboard(
                request,
                "dashboard/invalid.html",
                {"error": "Verify eSewa payment before fulfillment."},
                status=400,
            )
        if old != new:
            if field == "payment_status":
                try:
                    set_cod_payment_status(order.pk, new)
                except ValidationError as error:
                    return render_dashboard(
                        request,
                        "dashboard/invalid.html",
                        {"error": "; ".join(error.messages)},
                        status=400,
                    )
            else:
                updated = Order.objects.filter(
                    pk=order.pk, workflow_version=order.workflow_version
                ).update(**{field: new, "updated_at": timezone.now()})
                if updated != 1:
                    raise DatabaseError("Concurrent order update")
            StaffActivity.objects.create(
                staff=request.user,
                action=action,
                reference=order.order_number,
                description=f"{field}: {old} ? {new}",
            )
    messages.success(request, "Order updated successfully.")
    return redirect(
        f"{request.resolver_match.namespace}:order_detail", order_number=order_number
    )


@staff_required
@require_POST
def order_status(request, order_number):
    return update_status(
        request,
        order_number,
        "order_status",
        OrderStatusForm,
        StaffActivity.Action.ORDER_STATUS,
    )


@staff_required
@require_POST
def delivery_status(request, order_number):
    return update_status(
        request,
        order_number,
        "delivery_status",
        DeliveryStatusForm,
        StaffActivity.Action.DELIVERY_STATUS,
    )


@staff_required
@require_POST
def payment_status(request, order_number):
    return update_status(
        request,
        order_number,
        "payment_status",
        CODPaymentForm,
        StaffActivity.Action.PAYMENT_STATUS,
    )


@staff_required
@require_safe
def customers(request):
    customers = (
        get_user_model()
        .objects.filter(role="CUSTOMER")
        .annotate(order_count=Count("orders"))
        .order_by("username")
    )
    return render_dashboard(
        request, "dashboard/customers.html", {"customers": customers}
    )


def inventory_context(request, form=None):
    variants = ProductVariant.objects.select_related("product", "size", "color")
    if request.resolver_match.namespace != "owner":
        variants = variants.filter(is_active=True)
    query = request.GET.get("q", "").strip()
    if query:
        variants = variants.filter(
            Q(product__name__icontains=query) | Q(sku__icontains=query)
        )
    return {"variants": variants, "q": query, "form": form}


@staff_required
@require_safe
def inventory(request):
    return render_dashboard(
        request, "dashboard/inventory.html", inventory_context(request)
    )


@staff_required
@require_POST
def stock_adjustment(request):
    form = StockAdjustmentForm(request.POST)
    if request.resolver_match.namespace == "owner":
        form.fields["variant"].queryset = ProductVariant.objects.all()
    if form.is_valid():
        try:
            with transaction.atomic():
                variant = form.cleaned_data["variant"]
                record = adjust_stock(
                    variant,
                    form.cleaned_data["quantity_change"],
                    InventoryTransaction.TransactionType.ADJUSTMENT,
                    user=request.user,
                    reference=f"{request.user.role}-{request.user.pk}",
                    note=form.cleaned_data["note"]
                    or "Stock updated from inventory dashboard",
                    adjustment_key=form.cleaned_data["adjustment_key"],
                )
                StaffActivity.objects.create(
                    staff=request.user,
                    action=StaffActivity.Action.INVENTORY_ADJUSTMENT,
                    reference=variant.sku,
                    description=f"{record.quantity:+d}: {record.previous_stock} ? {record.new_stock}. {record.note}",
                )
        except ValidationError as error:
            form.add_error(None, error)
        except DatabaseError:
            form.add_error(None, "Stock changed concurrently. Please retry.")
        else:
            messages.success(request, "Stock adjusted successfully.")
            return redirect(f"{request.resolver_match.namespace}:inventory")
    return render_dashboard(
        request,
        "dashboard/inventory.html",
        inventory_context(request, form),
        status=400,
    )


@staff_required
@require_POST
def stock_update(request):
    form = StockUpdateForm(request.POST)
    if request.resolver_match.namespace == "owner":
        form.fields["variant"].queryset = ProductVariant.objects.all()
    if not form.is_valid():
        return JsonResponse(
            {
                "error": " ".join(
                    message for errors in form.errors.values() for message in errors
                )
            },
            status=400,
        )
    try:
        with transaction.atomic():
            variant, record = set_stock(
                form.cleaned_data["variant"],
                form.cleaned_data["quantity"],
                form.cleaned_data["expected_stock"],
                form.cleaned_data["expected_updated_at"],
                request.user,
            )
            if record:
                StaffActivity.objects.create(
                    staff=request.user,
                    action=StaffActivity.Action.INVENTORY_ADJUSTMENT,
                    reference=variant.sku,
                    description=f"{record.quantity:+d}: {record.previous_stock} ? {record.new_stock}. {record.note}",
                )
    except StockConflict as error:
        return JsonResponse({"error": "; ".join(error.messages)}, status=409)
    except ValidationError as error:
        return JsonResponse({"error": "; ".join(error.messages)}, status=400)
    except DatabaseError:
        return JsonResponse(
            {
                "error": "Unable to save stock. Inventory may have changed; reload and retry."
            },
            status=409,
        )
    return JsonResponse(
        {
            "quantity": variant.stock_quantity,
            "updated_at": variant.updated_at.isoformat(),
            "stock_level": variant.stock_level,
            "message": "Stock saved." if record else "Stock unchanged.",
        }
    )


def render_dashboard(request, template, context=None, **kwargs):
    """Keep shared operation contexts while using the current dashboard templates."""
    if request.resolver_match.namespace == "owner":
        template = template.replace("dashboard/", "owner/")
    return django_render(request, template, context, **kwargs)
