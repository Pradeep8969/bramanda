from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from inventory.models import InventoryTransaction
from inventory.stock_levels import stock_level
from orders.models import Order, OrderItem
from products.models import Category, Color, Product, ProductVariant, Size
from .models import StaffActivity


class StaffDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.customer = users.create_user(username='buyer', first_name='Asha', last_name='Rai',
            email='asha@example.com', phone_number='9800000001', address='Kathmandu')
        cls.staff = users.create_user(username='operator', role='STAFF')
        cls.owner = users.create_user(username='businessowner', role='OWNER')
        category = Category.objects.create(name='Clothes')
        product = Product.objects.create(name='Test Shirt', category=category, price=500)
        size = Size.objects.create(name='M')
        color = Color.objects.create(name='Black')
        cls.variant = ProductVariant.objects.create(product=product, size=size, color=color,
            sku='TEST-M', stock_quantity=5)
        cls.order = Order.objects.create(customer=cls.customer, first_name='Asha', last_name='Rai',
            email='asha@example.com', phone_number='9812345678', shipping_address='Pokhara',
            subtotal=500, shipping_cost=100, grand_total=600)
        cls.item = OrderItem.objects.create(order=cls.order, product=product, variant=cls.variant,
            product_name='Historical Shirt', color_name='Black', size_name='M', sku='TEST-M',
            quantity=1, unit_price=500, subtotal=500)

    def setUp(self):
        self.client.force_login(self.staff)
        self.detail = f'/staff/orders/{self.order.order_number}/'

    def mutations(self):
        return [(self.detail + 'status/', {'order_status': 'PROCESSING'}),
                (self.detail + 'delivery/', {'delivery_status': 'SHIPPED'}),
                (self.detail + 'payment/', {'payment_status': 'PAID'}),
                ('/staff/inventory/adjust/', self.adjustment())]

    def pages(self):
        return ['/staff/', '/staff/orders/', self.detail, '/staff/customers/', '/staff/inventory/']

    def adjustment(self, quantity=10, **changes):
        data = {'variant': self.variant.pk, 'quantity_change': quantity, 'note': 'Received / damaged'}
        data.update(changes)
        return data

    def test_anonymous_denied_all_routes(self):
        self.client.logout()
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertTrue(self.client.get(url).url.startswith('/login/?next='))
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url, data).status_code, 302)

    def test_customer_denied_all_routes(self):
        self.client.force_login(self.customer)
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 403)
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertFalse(StaffActivity.objects.exists())

    def test_staff_allowed(self):
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_owner_allowed(self):
        self.client.force_login(self.owner)
        for url in self.pages():
            self.assertEqual(self.client.get(url).status_code, 200)
        for url, data in self.mutations():
            self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(StaffActivity.objects.filter(staff=self.owner).count(), 4)

    def test_superuser_customer_is_denied(self):
        self.customer.is_superuser = True
        self.customer.is_staff = True
        self.customer.save()
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get('/staff/').status_code, 403)

    def test_dashboard_counts(self):
        for status in Order.OrderStatus.values:
            Order.objects.create(customer=self.customer, first_name='A', last_name='B', email='a@b.com',
                phone_number='98', shipping_address='City', subtotal=0, shipping_cost=100,
                grand_total=100, order_status=status)
        old = Order.objects.get(order_status='CANCELLED')
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now()-timedelta(days=2))
        cards = dict(self.client.get('/staff/').context['cards'])
        for status, label in Order.OrderStatus.choices:
            if status != 'CANCELLED':
                self.assertEqual(cards[label + ' Orders'], 2 if status == 'CONFIRMED' else 1)
        self.assertEqual(cards['Orders Today'], 7)
        self.assertEqual(cards['Low Stock Variants'], 1)

    def test_low_stock_boundaries_and_inactive(self):
        for quantity, count in [(0, 0), (1, 1), (5, 1), (6, 0)]:
            ProductVariant.objects.filter(pk=self.variant.pk).update(stock_quantity=quantity)
            self.assertEqual(dict(self.client.get('/staff/').context['cards'])['Low Stock Variants'], count)
        self.variant.is_active = False
        self.variant.save()
        self.assertEqual(dict(self.client.get('/staff/').context['cards'])['Low Stock Variants'], 0)

    def test_list_and_search(self):
        self.assertContains(self.client.get('/staff/orders/'), self.order.order_number)
        for query in [self.order.order_number, 'buyer', 'Asha', 'Rai', '9800000001', '9812345678']:
            self.assertEqual(list(self.client.get('/staff/orders/', {'q': query}).context['orders']), [self.order])
        self.assertFalse(self.client.get('/staff/orders/', {'q': 'missing'}).context['orders'])

    def test_filters_and_combination(self):
        for field, value in [('order_status', 'CONFIRMED'), ('delivery_status', 'PENDING'), ('payment_status', 'PENDING')]:
            self.assertEqual(list(self.client.get('/staff/orders/', {field: value}).context['orders']), [self.order])
            self.assertFalse(self.client.get('/staff/orders/', {field: 'invalid'}).context['orders'])
        self.assertEqual(self.client.get('/staff/orders/', {'order_status': 'CONFIRMED', 'payment_status': 'PENDING'}).context['orders'].count(), 1)

    def test_newest_first(self):
        Order.objects.filter(pk=self.order.pk).update(created_at=timezone.now()-timedelta(days=1))
        newer = Order.objects.create(customer=self.customer, first_name='A', last_name='B',
            email='a@b.com', phone_number='98', shipping_address='City', subtotal=0, shipping_cost=100, grand_total=100)
        self.assertEqual(list(self.client.get('/staff/orders/').context['orders']), [newer, self.order])

    def test_detail_uses_snapshots_and_totals(self):
        self.variant.product.name = 'Changed'
        self.variant.product.save()
        for text in ['Historical Shirt', 'TEST-M', 'Black', 'Pokhara', 'Rs. 500.00', 'Rs. 100.00', 'Rs. 600.00', 'Cash on Delivery']:
            self.assertContains(self.client.get(self.detail), text)
        self.assertEqual(self.client.get('/staff/orders/missing/').status_code, 404)

    def test_order_status_update_and_activity(self):
        response = self.client.post(self.detail+'status/', {'order_status': 'PROCESSING'}, follow=True)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, 'PROCESSING')
        self.assertContains(response, 'Order updated successfully.')
        activity = StaffActivity.objects.get()
        self.assertEqual(activity.action, 'ORDER_STATUS')
        self.assertEqual(activity.staff, self.staff)
        self.assertEqual(activity.reference, self.order.order_number)
        self.assertIn('CONFIRMED', activity.description)

    def test_invalid_statuses_rejected(self):
        for suffix, field in [('status/', 'order_status'), ('delivery/', 'delivery_status'), ('payment/', 'payment_status')]:
            for value in ['INVALID', '', 'processing']:
                self.assertEqual(self.client.post(self.detail+suffix, {field: value}).status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, 'CONFIRMED')
        self.assertFalse(StaffActivity.objects.exists())

    def test_delivery_update_activity_and_customer_tracking(self):
        self.client.post(self.detail+'status/', {'order_status': 'PROCESSING'})
        self.client.post(self.detail+'delivery/', {'delivery_status': 'OUT_FOR_DELIVERY'})
        self.assertTrue(StaffActivity.objects.filter(action='DELIVERY_STATUS', staff=self.staff).exists())
        self.client.force_login(self.customer)
        response = self.client.get(f'/orders/{self.order.order_number}/')
        self.assertContains(response, 'Out for delivery')
        self.assertEqual(response.context['order'].tracking_steps[4]['state'], 'current')
        self.assertContains(self.client.get('/orders/'), 'Processing')

    def test_cod_paid_and_activity(self):
        self.client.post(self.detail+'payment/', {'payment_status': 'PAID'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assertEqual(StaffActivity.objects.get().action, 'PAYMENT_STATUS')
        self.client.post(self.detail+'payment/', {'payment_status': 'PAID'})
        self.assertEqual(StaffActivity.objects.count(), 1)

    def test_non_cod_rejected(self):
        Order.objects.filter(pk=self.order.pk).update(payment_method='CARD')
        self.assertEqual(self.client.post(self.detail+'payment/', {'payment_status': 'PAID'}).status_code, 400)
        self.assertFalse(StaffActivity.objects.exists())

    def test_financial_totals_and_user_fields_cannot_be_changed(self):
        for url, data in self.mutations():
            data.update(subtotal='1', shipping_cost='1', grand_total='2', unit_price='1',
                        customer=self.staff.pk, role='OWNER', password='hacked')
            self.client.post(url, data)
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual((self.order.subtotal, self.order.shipping_cost, self.order.grand_total), (Decimal(500), Decimal(100), Decimal(600)))
        self.assertEqual((self.item.unit_price, self.item.subtotal), (Decimal(500), Decimal(500)))
        self.assertEqual(self.order.customer, self.customer)
        self.assertEqual(self.customer.role, 'CUSTOMER')

    def test_mutations_post_only(self):
        for url, data in self.mutations():
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(self.client.put(url, data).status_code, 405)
        self.assertFalse(StaffActivity.objects.exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        for url, data in self.mutations():
            self.assertEqual(client.post(url, data).status_code, 403)
        response = client.get(self.detail)
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.detail+'status/', {'order_status': 'PROCESSING', 'csrfmiddlewaretoken': token}).status_code, 302)

    def test_customers_only_and_order_counts(self):
        response = self.client.get('/staff/customers/')
        self.assertEqual(list(response.context['customers']), [self.customer])
        self.assertEqual(response.context['customers'][0].order_count, 1)
        for text in ['buyer', 'Asha Rai', 'asha@example.com', '9800000001', 'Kathmandu']:
            self.assertContains(response, text)

    def test_customer_role_and_password_not_editable(self):
        original = self.customer.password
        self.assertEqual(self.client.post('/staff/customers/', {'role': 'OWNER', 'password': 'hacked', 'user': self.customer.pk}).status_code, 405)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, 'CUSTOMER')
        self.assertEqual(self.customer.password, original)
        self.assertEqual(self.client.get('/admin/accounts/user/').status_code, 302)

    def test_inventory_search_active_and_stock_levels(self):
        for query in ['Test Shirt', 'TEST-M']:
            self.assertEqual(list(self.client.get('/staff/inventory/', {'q': query}).context['variants']), [self.variant])
        self.assertEqual([stock_level(n) for n in [0, 1, 5, 6]], ['Out of Stock', 'Low Stock', 'Low Stock', 'In Stock'])
        self.variant.is_active = False
        self.variant.save()
        self.assertFalse(self.client.get('/staff/inventory/').context['variants'])

    def test_positive_adjustment_transaction_and_activity(self):
        self.assertRedirects(self.client.post('/staff/inventory/adjust/', self.adjustment()), '/staff/inventory/')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 15)
        record = InventoryTransaction.objects.get()
        self.assertEqual((record.quantity, record.previous_stock, record.new_stock), (10, 5, 15))
        self.assertEqual(record.created_by, self.staff)
        self.assertEqual(record.transaction_type, 'ADJUSTMENT')
        self.assertEqual(record.note, 'Received / damaged')
        self.assertEqual(StaffActivity.objects.get().action, 'INVENTORY_ADJUSTMENT')

    def test_negative_adjustment(self):
        self.client.post('/staff/inventory/adjust/', self.adjustment(-1))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 4)
        self.assertEqual(InventoryTransaction.objects.get().quantity, -1)

    def test_exact_zero_stock_allowed(self):
        self.client.post('/staff/inventory/adjust/', self.adjustment(-5))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 0)

    def test_negative_result_rejected(self):
        self.assertEqual(self.client.post('/staff/inventory/adjust/', self.adjustment(-6)).status_code, 400)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 5)
        self.assertFalse(InventoryTransaction.objects.exists())
        self.assertFalse(StaffActivity.objects.exists())

    def test_invalid_adjustments(self):
        for quantity in [0, '1.5', 'bad', 2147483648]:
            self.assertEqual(self.client.post('/staff/inventory/adjust/', self.adjustment(quantity)).status_code, 400)
        for changes in [{'variant': 99999}, {'note': ''}]:
            self.assertEqual(self.client.post('/staff/inventory/adjust/', self.adjustment(**changes)).status_code, 400)
        self.variant.is_active = False
        self.variant.save()
        self.assertEqual(self.client.post('/staff/inventory/adjust/', self.adjustment()).status_code, 400)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_stock_activity_failure_rolls_back_adjustment(self):
        from django.db import DatabaseError
        with patch('dashboard.views.StaffActivity.objects.create', side_effect=DatabaseError('failure')):
            self.assertEqual(self.client.post('/staff/inventory/adjust/', self.adjustment()).status_code, 400)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 5)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_navigation_roles(self):
        for user, owner, staff in [(self.customer, False, False), (self.staff, False, True), (self.owner, True, False)]:
            self.client.force_login(user)
            response = self.client.get('/')
            self.assertEqual('Staff Dashboard' in response.content.decode(), staff)
            self.assertEqual('Owner Dashboard' in response.content.decode(), owner)
        self.client.logout()
        self.assertNotContains(self.client.get('/'), 'Staff Dashboard')
