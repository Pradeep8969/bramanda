from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Sum, F
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe, require_http_methods
from django.utils import timezone

from inventory.models import InventoryTransaction
from inventory.stock_levels import LOW_STOCK_MAX
from orders.models import Order, OrderItem
from products.models import Product, Category, Size, Color, ProductVariant
from products.forms import ProductForm, CategoryForm, SizeForm, ColorForm, ProductVariantForm
from .models import StaffActivity
from .permissions import owner_required
from .owner_forms import StaffCreateForm, StaffEditForm, ReportFilterForm
from . import views as staff_views


def valid_orders(orders):
    return orders.exclude(order_status=Order.OrderStatus.CANCELLED)


def revenue_orders(orders):
    return valid_orders(orders).filter(payment_status=Order.PaymentStatus.PAID)


def revenue(orders):
    return revenue_orders(orders).aggregate(total=Sum('grand_total'))['total'] or Decimal('0.00')


def best_sellers(orders):
    # Group live products together after renames; fall back to the snapshot if deleted.
    return OrderItem.objects.filter(order__in=valid_orders(orders)).annotate(
        name=Coalesce('product__name', 'product_name')).values('product_id', 'name').annotate(
        units_sold=Sum('quantity'), revenue=Sum('subtotal')).order_by('-units_sold', 'name')[:10]


@owner_required
@require_safe
def home(request):
    orders = Order.objects.all()
    variants = ProductVariant.objects.filter(is_active=True)
    today = timezone.localdate()
    month = today.replace(day=1)
    cards = [('Total Revenue', revenue(orders)), ('Total Orders', orders.count()),
        ('Total Customers', get_user_model().objects.filter(role='CUSTOMER').count()),
        ('Total Products', Product.objects.count()), ('Total Active Products', Product.objects.filter(is_active=True).count())]
    cards += [(label + ' Orders', orders.filter(order_status=status).count()) for status, label in
        [('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('DELIVERED', 'Delivered')]]
    cards += [('Paid Orders', orders.filter(payment_status='PAID').count()),
        ('Low Stock Variants', variants.filter(stock_quantity__gte=1, stock_quantity__lte=LOW_STOCK_MAX).count()),
        ('Out of Stock Variants', variants.filter(stock_quantity=0).count()),
        ('Sales Today', revenue(orders.filter(created_at__date=today))),
        ('Sales This Month', revenue(orders.filter(created_at__date__gte=month, created_at__date__lte=today))),
        ('Orders Today', orders.filter(created_at__date=today).count()),
        ('Orders This Month', orders.filter(created_at__date__gte=month, created_at__date__lte=today).count())]
    days = [today-timedelta(days=n) for n in reversed(range(7))]
    daily = [{'date': day, 'sales': revenue(orders.filter(created_at__date=day)),
        'orders': orders.filter(created_at__date=day).count()} for day in days]
    max_sales = max((row['sales'] for row in daily), default=0) or 1
    max_orders = max((row['orders'] for row in daily), default=0) or 1
    for row in daily:
        row['sales_width'] = float(row['sales'] / max_sales * 100)
        row['orders_width'] = row['orders'] / max_orders * 100
    return render(request, 'owner/home.html', {'cards': cards, 'daily': daily,
        'orders': orders.select_related('customer')[:8], 'best_sellers': best_sellers(orders),
        'inventory_activity': InventoryTransaction.objects.select_related('variant__product', 'created_by')[:8],
        'activities': StaffActivity.objects.select_related('staff')[:8]})


@owner_required
@require_safe
def reports(request):
    form = ReportFilterForm(request.GET)
    orders = Order.objects.all()
    if form.is_valid():
        for key, lookup in [('from_date', 'created_at__date__gte'), ('to_date', 'created_at__date__lte')]:
            if form.cleaned_data.get(key):
                orders = orders.filter(**{lookup: form.cleaned_data[key]})
    else:
        orders = orders.none()
    paid = revenue_orders(orders)
    metrics = {'revenue': revenue(orders), 'order_count': valid_orders(orders).count(),
        'average_order_value': paid.aggregate(value=Avg('grand_total'))['value'] or Decimal('0.00'),
        'delivered_count': orders.filter(order_status='DELIVERED').count(),
        'cancelled_count': orders.filter(order_status='CANCELLED').count()}
    return render(request, 'owner/reports.html', {'form': form, 'metrics': metrics,
        'best_sellers': best_sellers(orders)}, status=200 if form.is_valid() else 400)


CATALOG = {'products': (Product, ProductForm), 'categories': (Category, CategoryForm),
    'sizes': (Size, SizeForm), 'colors': (Color, ColorForm), 'variants': (ProductVariant, ProductVariantForm)}


@owner_required
@require_safe
def catalog_list(request, kind):
    model, _ = CATALOG[kind]
    objects = model.objects.all()
    if kind == 'products':
        objects = objects.select_related('category')
    if kind == 'variants':
        objects = objects.select_related('product', 'size', 'color')
    return render(request, 'owner/catalog.html', {'objects': objects, 'kind': kind})


@owner_required
@require_http_methods(['GET', 'POST'])
def catalog_edit(request, kind, pk=None):
    model, form_class = CATALOG[kind]
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST if request.method == 'POST' else None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('owner:' + kind)
    return render(request, 'owner/form.html', {'form': form, 'title': ('Edit ' if pk else 'Add ') + kind},
        status=400 if request.method == 'POST' else 200)


@owner_required
@require_POST
def catalog_toggle(request, kind, pk):
    model, _ = CATALOG[kind]
    obj = get_object_or_404(model, pk=pk)
    model.objects.filter(pk=obj.pk).update(is_active=~F('is_active'))
    return redirect('owner:' + kind)


@owner_required
@require_safe
def staff_list(request):
    return render(request, 'owner/staff.html', {'staff_users': get_user_model().objects.filter(role='STAFF').order_by('username')})


@owner_required
@require_http_methods(['GET', 'POST'])
def staff_edit(request, pk=None):
    instance = get_object_or_404(get_user_model(), pk=pk, role='STAFF') if pk else None
    form = (StaffEditForm if pk else StaffCreateForm)(request.POST if request.method == 'POST' else None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('owner:staff')
    return render(request, 'owner/form.html', {'form': form, 'title': 'Edit staff' if pk else 'Create staff'},
        status=400 if request.method == 'POST' else 200)


@owner_required
@require_POST
def staff_toggle(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, role='STAFF')
    get_user_model().objects.filter(pk=user.pk, role='STAFF').update(is_active=~F('is_active'))
    return redirect('owner:staff')


@owner_required
@require_safe
def payments(request):
    orders = Order.objects.select_related('customer')
    filters = []
    for field, choices in [('payment_status', Order.PaymentStatus.choices), ('payment_method', Order.PaymentMethod.choices)]:
        value = request.GET.get(field, '')
        if value:
            orders = orders.filter(**{field: value})
        filters.append((field, field.replace('_', ' ').title(), choices, value))
    return render(request, 'owner/payments.html', {'orders': orders, 'filters': filters})


@owner_required
@require_safe
def activity(request):
    records = StaffActivity.objects.select_related('staff')
    staff = request.GET.get('staff', '')
    action = request.GET.get('action', '')
    if staff:
        records = records.filter(staff_id=staff) if staff.isdigit() else records.none()
    if action:
        records = records.filter(action=action)
    form = ReportFilterForm(request.GET)
    if form.is_valid():
        for key, lookup in [('from_date', 'created_at__date__gte'), ('to_date', 'created_at__date__lte')]:
            if form.cleaned_data.get(key):
                records = records.filter(**{lookup: form.cleaned_data[key]})
    else:
        records = records.none()
    return render(request, 'owner/activity.html', {'activities': records, 'form': form,
        'selected_staff': staff, 'selected_action': action, 'actions': StaffActivity.Action.choices,
        'staff_users': get_user_model().objects.filter(role__in=['STAFF', 'OWNER'])})


# Owner guard runs before the existing staff guards and shared operations.
order_list = owner_required(staff_views.order_list)
order_detail = owner_required(staff_views.order_detail)
order_status = owner_required(staff_views.order_status)
delivery_status = owner_required(staff_views.delivery_status)
payment_status = owner_required(staff_views.payment_status)
customers = owner_required(staff_views.customers)
inventory = owner_required(staff_views.inventory)
stock_adjustment = owner_required(staff_views.stock_adjustment)
