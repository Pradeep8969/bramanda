"""Run via: python manage.py shell -c "exec(open('scripts/verify_customer_flow.py').read())".
Uses the real seeded catalog, but rolls back all customer/cart/session changes.
"""
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, override_settings
from django.urls import reverse

from cart.models import Cart, CartItem
from inventory.models import InventoryTransaction
from products.models import ProductVariant

with override_settings(ALLOWED_HOSTS=['testserver']), transaction.atomic():
    client = Client()
    for url in ('/', '/shop/', '/register/', '/login/'):
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        print(f'GET {url}: 200')
    for url in ('/profile/', '/cart/'):
        response = client.get(url)
        assert response.status_code == 302 and response.url.startswith('/login/')
        print(f'Anonymous GET {url}: redirects to login')

    username = 'verify_' + uuid4().hex[:12]
    password = 'Bramanda-Test-Flow-845!'
    response = client.post('/register/', {
        'username': username, 'first_name': 'Verification', 'last_name': 'Customer',
        'email': 'verification@example.com', 'phone_number': '9800000000',
        'address': 'Kathmandu', 'password1': password, 'password2': password,
        'role': 'OWNER',
    })
    assert response.status_code == 302, response.context['form'].errors
    user = get_user_model().objects.get(username=username)
    assert user.role == 'CUSTOMER' and user.check_password(password)
    print('Registration: CUSTOMER created, hashed password, automatically logged in')
    assert client.post('/logout/').status_code == 302
    response = client.post('/login/', {'username': username, 'password': password})
    assert response.status_code == 302 and client.session['_auth_user_id'] == str(user.pk)
    print('Logout and username/password login: successful')
    for url in ('/profile/', '/cart/'):
        assert client.get(url).status_code == 200
        print(f'Authenticated GET {url}: 200')

    variant = ProductVariant.objects.get(product__slug='bramanda-oversized-t-shirt', color__name='Black', size__name='M')
    assert variant.stock_quantity >= 2
    stock_before = variant.stock_quantity
    inventory_before = InventoryTransaction.objects.count()
    product_url = reverse('products:detail', args=[variant.product.slug])
    assert client.get(product_url).status_code == 200
    response = client.post(reverse('cart:add', args=[variant.product.slug]), {'variant': variant.pk, 'quantity': 2})
    assert response.status_code == 302 and response.url == '/cart/'
    item = CartItem.objects.get(cart__user=user)
    assert item.unit_price == Decimal('845.00')
    assert item.quantity == 2 and item.subtotal == Decimal('1690.00')
    cart = Cart.objects.get(user=user)
    assert cart.subtotal == Decimal('1690.00') and cart.total_items == 2
    response = client.get('/cart/')
    assert 'Rs. 1690.00' in response.content.decode() and 'Cart (2)' in response.content.decode()
    variant.refresh_from_db()
    assert variant.stock_quantity == stock_before and InventoryTransaction.objects.count() == inventory_before
    print(f'Black / M: Rs. 845.00 × 2 = Rs. 1690.00; stock unchanged ({stock_before}); inventory ledger unchanged')

    assert client.post(reverse('cart:update', args=[item.pk]), {'quantity': 1}).status_code == 302
    item.refresh_from_db()
    assert item.quantity == 1 and item.subtotal == Decimal('845.00')
    assert client.post(reverse('cart:remove', args=[item.pk])).status_code == 302
    assert not CartItem.objects.filter(cart__user=user).exists()
    assert 'Your cart is empty.' in client.get('/cart/').content.decode()
    print('Quantity update and POST removal: successful')
    transaction.set_rollback(True)
    print('Verification data rolled back; seeded catalog unchanged')

