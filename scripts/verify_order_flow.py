"""Run with manage.py shell; all verification writes are rolled back."""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings
from django.test.utils import setup_test_environment
from django.urls import reverse

from cart.models import Cart, CartItem
from inventory.models import InventoryTransaction
from orders.models import Order
from products.models import ProductVariant

setup_test_environment()

variant = ProductVariant.objects.get(product__slug='bramanda-oversized-t-shirt', color__name='Black', size__name='M')
stock_before = variant.stock_quantity
assert stock_before == 20, f'Expected seeded stock 20; found {stock_before}'
username = 'verify_order_' + uuid4().hex[:10]
orders_before = Order.objects.count()
ledger_before = InventoryTransaction.objects.count()

with override_settings(ALLOWED_HOSTS=['testserver']), transaction.atomic():
    client = Client()
    password = 'Bramanda-Order-Flow-845!'
    response = client.post('/register/', {
        'username': username, 'first_name': 'Verification', 'last_name': 'Customer',
        'email': 'verification@example.com', 'phone_number': '9800000000', 'address': 'Kathmandu',
        'password1': password, 'password2': password,
    })
    assert response.status_code == 302
    user = get_user_model().objects.get(username=username)
    assert user.role == 'CUSTOMER'
    client.post('/logout/')
    assert client.post('/login/', {'username': username, 'password': password}).status_code == 302
    print('Customer registration, logout and login: passed')

    detail_url = reverse('products:detail', args=[variant.product.slug])
    assert client.get(detail_url).status_code == 200
    assert client.post(reverse('cart:add', args=[variant.product.slug]), {'variant': variant.pk, 'quantity': 2}).status_code == 302
    cart = Cart.objects.get(user=user)
    assert cart.subtotal == Decimal('1690.00')
    assert 'Rs. 1690.00' in client.get('/cart/').content.decode()
    variant.refresh_from_db()
    assert variant.stock_quantity == 20
    print('Black / M quantity 2; cart subtotal Rs. 1690.00; stock remains 20')

    response = client.get('/checkout/')
    assert response.status_code == 200
    assert response.context['grand_total'] == Decimal('1790.00')
    assert response.context['form'].initial['shipping_address'] == 'Kathmandu'
    print('Checkout: profile prefill, COD, Rs. 100.00 shipping; grand total Rs. 1790.00')
    response = client.post('/checkout/', {
        'first_name': 'Verification', 'last_name': 'Customer', 'email': 'verification@example.com',
        'phone_number': '9800000000', 'shipping_address': 'Pokhara, Lakeside', 'payment_method': 'COD',
    })
    order = Order.objects.get(customer=user)
    assert response.status_code == 302 and response.url == reverse('orders:success', args=[order.order_number])
    assert 'Order Confirmed' in client.get(response.url).content.decode()
    assert order.payment_status == 'PENDING' and order.order_status == 'CONFIRMED'
    assert order.grand_total == Decimal('1790.00')
    assert order.items.get().subtotal == Decimal('1690.00')
    print(f'Order success: {order.order_number}; COD payment remains PENDING')
    assert not CartItem.objects.filter(cart=cart).exists()
    assert 'Cart (0)' in client.get('/cart/').content.decode()
    variant.refresh_from_db()
    assert variant.stock_quantity == 18
    record = InventoryTransaction.objects.get(transaction_type='ORDER', reference=order.order_number)
    assert (record.quantity, record.previous_stock, record.new_stock) == (-2, 20, 18)
    print('Cart cleared; stock 20 -> 18; ORDER inventory audit: quantity -2, previous 20, new 18')

    assert order.order_number in client.get('/orders/').content.decode()
    detail = client.get(reverse('orders:detail', args=[order.order_number]))
    assert detail.status_code == 200
    assert 'Current stage' in detail.content.decode() and 'Confirmed' in detail.content.decode()
    print('My Orders, private order detail, snapshots and tracking: passed')
    transaction.set_rollback(True)

variant.refresh_from_db()
assert variant.stock_quantity == stock_before == 20
assert Order.objects.count() == orders_before
assert InventoryTransaction.objects.count() == ledger_before
assert not get_user_model().objects.filter(username=username).exists()
print('Verification rolled back: sample Black / M stock is 20; no verification user/order/audit remains')

