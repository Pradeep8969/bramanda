"""Run with: python manage.py shell -c "exec(open('scripts/verify_staff_dashboard.py', encoding='utf-8').read())".
All verification data and changes roll back, preserving the local database.
"""
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings
from inventory.models import InventoryTransaction
from dashboard.models import StaffActivity
from orders.models import Order, OrderItem
from products.models import Category, Color, Size, Product, ProductVariant

with override_settings(ALLOWED_HOSTS=['testserver']), transaction.atomic():
    suffix = uuid4().hex[:10]
    users = get_user_model().objects
    staff = users.create_user(username='verify-staff-' + suffix, password='Temporary-Verify-2026!', role='STAFF')
    owner = users.create_user(username='verify-owner-' + suffix, password='Temporary-Verify-2026!', role='OWNER')
    customer = users.create_user(username='verify-customer-' + suffix, password='Temporary-Verify-2026!')
    category = Category.objects.create(name='Verification-' + suffix)
    product = Product.objects.create(name='Verification shirt', category=category, price=500)
    color = Color.objects.create(name='Verify-' + suffix)
    size = Size.objects.create(name='V-' + suffix)
    variant = ProductVariant.objects.create(product=product, color=color, size=size, sku='VERIFY-' + suffix, stock_quantity=5)
    order = Order.objects.create(customer=customer, first_name='Test', last_name='Customer', email='test@example.com',
        phone_number='9800000000', shipping_address='Kathmandu', subtotal=500, shipping_cost=100, grand_total=600)
    OrderItem.objects.create(order=order, product=product, variant=variant, product_name=product.name,
        size_name=size.name, color_name=color.name, sku=variant.sku, quantity=1, unit_price=500, subtotal=500)
    client = Client(enforce_csrf_checks=True)
    assert client.login(username=staff.username, password='Temporary-Verify-2026!')
    assert client.get('/staff/').status_code == 200
    detail = f'/staff/orders/{order.order_number}/'
    assert client.get(detail).status_code == 200
    token = client.cookies['csrftoken'].value
    assert client.post(detail + 'status/', {'order_status': 'PROCESSING', 'csrfmiddlewaretoken': token}).status_code == 302
    assert client.post(detail + 'delivery/', {'delivery_status': 'SHIPPED', 'csrfmiddlewaretoken': token}).status_code == 302
    viewer = Client()
    assert viewer.login(username=customer.username, password='Temporary-Verify-2026!')
    tracking = viewer.get(f'/orders/{order.order_number}/').content.decode()
    assert 'Processing' in tracking and 'Shipped' in tracking
    assert client.get('/staff/inventory/').status_code == 200
    assert client.post('/staff/inventory/adjust/', {'variant': variant.pk, 'quantity_change': 10,
        'note': 'Verification receipt', 'csrfmiddlewaretoken': token}).status_code == 302
    variant.refresh_from_db()
    assert variant.stock_quantity == 15
    assert InventoryTransaction.objects.filter(variant=variant, created_by=staff, quantity=10).exists()
    assert StaffActivity.objects.filter(staff=staff).count() == 3
    assert client.post(detail + 'payment/', {'payment_status': 'PAID', 'csrfmiddlewaretoken': token}).status_code == 302
    assert StaffActivity.objects.filter(staff=staff, action='PAYMENT_STATUS').exists()
    assert client.login(username=owner.username, password='Temporary-Verify-2026!')
    assert client.get('/staff/').status_code == 200
    print('PASS: STAFF login, dashboard, order processing, delivery, customer tracking, inventory, transaction, activity, COD, OWNER login.')
    transaction.set_rollback(True)
print('Verification changes rolled back; existing data preserved.')
