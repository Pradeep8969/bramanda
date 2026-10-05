from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from cart.models import Cart, CartItem
from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from products.models import Category, Color, Product, ProductVariant, Size
from .forms import CheckoutForm
from .models import Order, OrderItem
from .services import SHIPPING_COST, create_order_from_cart


class CheckoutOrderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='buyer', first_name='Asha', last_name='Rai', email='asha@example.com',
            phone_number='9800000001', address='Kathmandu',
        )
        cls.other = get_user_model().objects.create_user(username='other')
        cls.category = Category.objects.create(name='T-Shirts')
        cls.size = Size.objects.create(name='M')
        cls.color = Color.objects.create(name='Black')
        cls.product = Product.objects.create(name='Bramanda Oversized T-Shirt', category=cls.category, price=Decimal('845.00'))
        cls.variant = ProductVariant.objects.create(product=cls.product, size=cls.size, color=cls.color, sku='BRM-BLACK-M', stock_quantity=20)
        cls.cart = Cart.objects.create(user=cls.user)
        cls.cart_item = CartItem.objects.create(cart=cls.cart, variant=cls.variant, quantity=2)

    def setUp(self):
        self.client.force_login(self.user)

    def data(self, **changes):
        data = {'first_name': 'Asha', 'last_name': 'Rai', 'email': 'asha@example.com',
                'phone_number': '9800000001', 'shipping_address': 'Pokhara, Lakeside',
                'payment_method': 'COD'}
        data.update(changes)
        return data

    def place(self, **changes):
        return create_order_from_cart(self.user, self.cart, self.data(**changes))

    def add_second_item(self, stock=5, quantity=2):
        size = Size.objects.create(name='L')
        variant = ProductVariant.objects.create(product=self.product, size=size, color=self.color, sku='BRM-BLACK-L', stock_quantity=stock)
        CartItem.objects.create(cart=self.cart, variant=variant, quantity=quantity)
        return variant

    def assert_no_order_or_stock_change(self, stock=20, items=1):
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertFalse(InventoryTransaction.objects.filter(transaction_type='ORDER').exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, stock)
        self.assertEqual(self.cart.items.count(), items)

    def test_checkout_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get('/checkout/'), '/login/?next=/checkout/')

    def test_empty_cart_redirects_with_message(self):
        self.cart.items.all().delete()
        response = self.client.get('/checkout/', follow=True)
        self.assertRedirects(response, '/cart/')
        self.assertContains(response, 'Add a product before checking out')

    def test_no_cart_redirects(self):
        self.client.force_login(self.other)
        self.assertRedirects(self.client.get('/checkout/'), '/cart/')

    def test_checkout_items_totals_and_profile_prefill(self):
        response = self.client.get('/checkout/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)
        self.assertContains(response, 'Black / M')
        self.assertContains(response, 'Rs. 1690.00')
        self.assertEqual(response.context['subtotal'], Decimal('1690.00'))
        self.assertEqual(response.context['shipping_cost'], Decimal('100.00'))
        self.assertEqual(response.context['grand_total'], Decimal('1790.00'))
        for field, value in {'first_name': 'Asha', 'last_name': 'Rai', 'email': 'asha@example.com',
                             'phone_number': '9800000001', 'shipping_address': 'Kathmandu'}.items():
            self.assertEqual(response.context['form'].initial[field], value)
        self.assertContains(response, 'Cash on Delivery')

    def test_checkout_get_does_not_create_order_or_change_stock(self):
        self.client.get('/checkout/')
        self.assert_no_order_or_stock_change()

    def test_checkout_form_validates_required_details_and_cod_only(self):
        for field in self.data():
            with self.subTest(field=field):
                data = self.data()
                data[field] = ''
                self.assertFalse(CheckoutForm(data).is_valid())
        self.assertFalse(CheckoutForm(self.data(payment_method='CARD')).is_valid())
        self.assertFalse(CheckoutForm(self.data(email='invalid')).is_valid())
        self.assertFalse(CheckoutForm(self.data(phone_number='words')).is_valid())

    def test_successful_post_redirects_to_success_and_preserves_profile(self):
        response = self.client.post('/checkout/', self.data())
        order = Order.objects.get()
        self.assertRedirects(response, reverse('orders:success', args=[order.order_number]))
        self.assertEqual(order.shipping_address, 'Pokhara, Lakeside')
        self.user.refresh_from_db()
        self.assertEqual(self.user.address, 'Kathmandu')
        self.assertContains(self.client.get(response.url), 'Order Confirmed')

    def test_server_ignores_spoofed_totals_customer_and_status(self):
        self.client.post('/checkout/', self.data(subtotal='0.01', grand_total='0.01', shipping_cost='0',
                                                customer=self.other.pk, payment_status='PAID', order_status='DELIVERED'))
        order = Order.objects.get()
        self.assertEqual(order.customer, self.user)
        self.assertEqual(order.subtotal, Decimal('1690.00'))
        self.assertEqual(order.shipping_cost, SHIPPING_COST)
        self.assertEqual(order.grand_total, Decimal('1790.00'))
        self.assertEqual(order.payment_method, 'COD')
        self.assertEqual(order.payment_status, 'PENDING')
        self.assertEqual(order.order_status, 'CONFIRMED')
        self.assertEqual(order.delivery_status, 'PENDING')

    def test_order_item_snapshots_and_totals(self):
        order = self.place()
        item = order.items.get()
        self.assertEqual(item.product, self.product)
        self.assertEqual(item.variant, self.variant)
        self.assertEqual(item.product_name, 'Bramanda Oversized T-Shirt')
        self.assertEqual(item.color_name, 'Black')
        self.assertEqual(item.size_name, 'M')
        self.assertEqual(item.sku, 'BRM-BLACK-M')
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal('845.00'))
        self.assertEqual(item.subtotal, Decimal('1690.00'))
        self.assertEqual(order.subtotal, Decimal('1690.00'))
        self.assertEqual(order.shipping_cost, Decimal('100.00'))
        self.assertEqual(order.grand_total, Decimal('1790.00'))

    def test_unique_order_numbers(self):
        first = self.place()
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=1)
        second = self.place()
        self.assertNotEqual(first.order_number, second.order_number)
        self.assertRegex(first.order_number, r'^BRM-\d{8}-[A-F0-9]{16}$')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Order.objects.create(order_number=first.order_number, customer=self.user,
                                 **self.data(), subtotal=0, shipping_cost=0, grand_total=0)

    def test_inventory_audit_and_cart_clear(self):
        order = self.place()
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 18)
        record = InventoryTransaction.objects.get(transaction_type='ORDER')
        self.assertEqual(record.variant, self.variant)
        self.assertEqual(record.quantity, -2)
        self.assertEqual(record.previous_stock, 20)
        self.assertEqual(record.new_stock, 18)
        self.assertEqual(record.reference, order.order_number)
        self.assertEqual(record.created_by, self.user)
        self.assertFalse(self.cart.items.exists())
        self.assertTrue(Cart.objects.filter(pk=self.cart.pk).exists())
        self.assertContains(self.client.get('/shop/'), 'Cart (0)')

    def test_database_price_is_refetched(self):
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('900.00'))
        order = self.place()
        self.assertEqual(order.items.get().unit_price, Decimal('900.00'))
        self.assertEqual(order.subtotal, Decimal('1800.00'))

    def test_fractional_prices_use_decimal(self):
        Product.objects.filter(pk=self.product.pk).update(price=Decimal('0.10'))
        CartItem.objects.filter(pk=self.cart_item.pk).update(quantity=3)
        order = self.place()
        self.assertEqual(order.items.get().subtotal, Decimal('0.30'))
        self.assertEqual(order.grand_total, Decimal('100.30'))

    def test_insufficient_stock_rolls_back_whole_cart(self):
        second = self.add_second_item(stock=1, quantity=2)
        with self.assertRaisesMessage(ValidationError, 'Only 1 item(s)'):
            self.place()
        self.assert_no_order_or_stock_change(items=2)
        second.refresh_from_db()
        self.assertEqual(second.stock_quantity, 1)

    def test_inventory_failure_after_first_debit_rolls_back_everything(self):
        second = self.add_second_item()
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args[0].pk)
            if len(calls) == 2:
                raise ValidationError('Stock changed concurrently. Please retry.')
            return adjust_stock(*args, **kwargs)

        with patch('orders.services.adjust_stock', side_effect=fail_second):
            with self.assertRaises(ValidationError):
                self.place()
        self.assertEqual(len(calls), 2)
        self.assert_no_order_or_stock_change(items=2)
        second.refresh_from_db()
        self.assertEqual(second.stock_quantity, 5)

    def test_insufficient_stock_view_shows_friendly_error(self):
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock_quantity=1)
        response = self.client.post('/checkout/', self.data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only 1 item(s) are currently available for Black / M.')
        self.assert_no_order_or_stock_change(stock=1)

    def test_inactive_catalog_entries_rejected_at_checkout(self):
        for obj in (self.variant, self.product, self.category, self.size, self.color):
            with self.subTest(model=type(obj).__name__):
                obj.is_active = False
                obj.save()
                with self.assertRaisesMessage(ValidationError, 'no longer available'):
                    self.place()
                self.assert_no_order_or_stock_change()
                obj.is_active = True
                obj.save()

    def test_final_stock_cannot_be_purchased_twice(self):
        ProductVariant.objects.filter(pk=self.variant.pk).update(stock_quantity=2)
        other_cart = Cart.objects.create(user=self.other)
        CartItem.objects.create(cart=other_cart, variant=self.variant, quantity=1)
        self.place()
        with self.assertRaisesMessage(ValidationError, 'Only 0 item(s)'):
            create_order_from_cart(self.other, other_cart, self.data())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 0)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(other_cart.items.get().quantity, 1)

    def test_service_rejects_foreign_cart(self):
        with self.assertRaisesMessage(ValidationError, 'does not belong'):
            create_order_from_cart(self.other, self.cart, self.data())
        self.assert_no_order_or_stock_change()

    def test_service_rejects_empty_cart(self):
        self.cart.items.all().delete()
        with self.assertRaisesMessage(ValidationError, 'empty'):
            self.place()
        self.assert_no_order_or_stock_change(items=0)

    def test_service_rejects_invalid_shipping_and_payment(self):
        for data in (self.data(payment_method='CARD'), self.data(first_name='')):
            with self.assertRaises(ValidationError):
                create_order_from_cart(self.user, self.cart, data)
        self.assert_no_order_or_stock_change()

    def test_double_submit_does_not_duplicate_order(self):
        self.client.post('/checkout/', self.data())
        response = self.client.post('/checkout/', self.data())
        self.assertRedirects(response, '/cart/')
        self.assertEqual(Order.objects.count(), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 18)

    def test_invalid_form_preserves_cart_and_stock(self):
        response = self.client.post('/checkout/', self.data(email='wrong'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assert_no_order_or_stock_change()

    def test_sqlite_write_conflict_shows_retry_message(self):
        with patch('orders.views.create_order_from_cart', side_effect=OperationalError('database is locked')):
            response = self.client.post('/checkout/', self.data())
        self.assertContains(response, 'Please try again.')
        self.assert_no_order_or_stock_change()

    def test_checkout_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/checkout/', self.data()).status_code, 403)
        self.assert_no_order_or_stock_change()

    def test_order_pages_require_login(self):
        order = self.place()
        self.client.logout()
        for url in ('/orders/', reverse('orders:detail', args=[order.order_number]),
                    reverse('orders:success', args=[order.order_number])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith('/login/'))

    def test_customer_can_view_own_order_pages(self):
        order = self.place()
        self.assertContains(self.client.get('/orders/'), order.order_number)
        detail = self.client.get(reverse('orders:detail', args=[order.order_number]))
        for text in (order.order_number, 'Bramanda Oversized T-Shirt', 'Black / M', 'Pokhara, Lakeside',
                     'Rs. 1790.00', 'Cash on Delivery', 'Pending', 'Current stage'):
            self.assertContains(detail, text)
        self.assertContains(self.client.get(reverse('orders:success', args=[order.order_number])), order.order_number)

    def test_foreign_and_missing_order_pages_return_404(self):
        order = self.place()
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get('/orders/'), order.order_number)
        for name in ('orders:detail', 'orders:success'):
            self.assertEqual(self.client.get(reverse(name, args=[order.order_number])).status_code, 404)
            self.assertEqual(self.client.get(reverse(name, args=['missing'])).status_code, 404)

    def test_order_list_newest_first(self):
        first = self.place()
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=1)
        second = self.place()
        self.assertEqual(list(self.client.get('/orders/').context['orders']), [second, first])

    def test_empty_order_history(self):
        self.assertContains(self.client.get('/orders/'), 'No orders yet.')

    def test_history_remains_unchanged_after_catalog_edits(self):
        order = self.place()
        Product.objects.filter(pk=self.product.pk).update(name='Renamed Product', price=Decimal('900.00'), is_active=False)
        Color.objects.filter(pk=self.color.pk).update(name='Renamed Color')
        Size.objects.filter(pk=self.size.pk).update(name='Renamed Size')
        ProductVariant.objects.filter(pk=self.variant.pk).update(sku='NEW-SKU')
        item = order.items.get()
        self.assertEqual(item.unit_price, Decimal('845.00'))
        self.assertEqual(item.product_name, 'Bramanda Oversized T-Shirt')
        self.assertEqual(item.color_name, 'Black')
        self.assertEqual(item.size_name, 'M')
        self.assertEqual(item.sku, 'BRM-BLACK-M')
        self.assertEqual(item.subtotal, Decimal('1690.00'))
        self.assertContains(self.client.get(reverse('orders:detail', args=[order.order_number])), 'Bramanda Oversized T-Shirt')
        # Snapshot display also works if catalog references are removed.
        order.items.update(product=None, variant=None)
        self.assertContains(self.client.get(reverse('orders:detail', args=[order.order_number])), 'Black / M')

    def test_existing_inventory_audit_protects_catalog_deletion(self):
        self.place()
        with self.assertRaises(ProtectedError):
            self.variant.delete()

    def test_tracking_uses_order_and_delivery_status_and_handles_cancellation(self):
        order = self.place()
        self.assertEqual(order.tracking_steps[0]['state'], 'current')
        order.order_status = 'SHIPPED'
        order.delivery_status = 'OUT_FOR_DELIVERY'
        self.assertEqual(order.tracking_steps[4]['state'], 'current')
        self.assertEqual(order.tracking_steps[3]['state'], 'complete')
        order.delivery_status = 'DELIVERED'
        self.assertEqual(order.tracking_steps[5]['state'], 'current')
        order.order_status = 'CANCELLED'
        order.save()
        self.assertEqual(order.tracking_steps, [])
        self.assertContains(self.client.get(reverse('orders:detail', args=[order.order_number])), 'This order has been cancelled.')

    def test_order_admin_preserves_financial_and_snapshot_fields(self):
        order_admin = admin.site._registry[Order]
        item_admin = admin.site._registry[OrderItem]
        for field in ('subtotal', 'shipping_cost', 'grand_total', 'customer', 'order_number'):
            self.assertIn(field, order_admin.readonly_fields)
        self.assertIn('unit_price', item_admin.readonly_fields)
        self.assertIn('product_name', item_admin.readonly_fields)

