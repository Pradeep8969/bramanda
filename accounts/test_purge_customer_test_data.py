from io import StringIO
from contextlib import contextmanager
from unittest.mock import patch

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.core.management import call_command
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
from django.db import connection

from accounts.management.commands.purge_customer_test_data import Command, TEST_ORDER_NUMBERS
from accounts.models import User
from cart.models import Cart, CartItem
from dashboard.models import StaffActivity
from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from orders.models import Order, OrderItem
from orders.services import create_order_from_cart
from products.models import Category, Color, Product, ProductImage, ProductVariant, Size
from payments.models import Payment


class PurgeCustomerTestDataTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='buyer', email='buyer@example.com')
        self.owner = User.objects.create_user(username='owner', role='OWNER')
        self.staff = User.objects.create_user(username='staff', role='STAFF')
        self.admin = User.objects.create_user(username='admin', is_staff=True)
        self.superuser = User.objects.create_superuser(username='superuser', password='test-password')
        self.protected = [self.owner, self.staff, self.admin, self.superuser]
        self.category = Category.objects.create(name='Shirts')
        self.size = Size.objects.create(name='M')
        self.color = Color.objects.create(name='Black')
        self.product = Product.objects.create(name='Shirt', category=self.category, price=100, image='products/test.jpg')
        self.image = ProductImage.objects.create(product=self.product, image='products/gallery/test.jpg')
        self.variant = ProductVariant.objects.create(product=self.product, size=self.size, color=self.color,
                                                     sku='PURGE-M', stock_quantity=20)
        self.cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=3)
        self.order = create_order_from_cart(self.customer, self.cart, {
            'first_name': 'Buyer', 'last_name': 'Test', 'email': self.customer.email,
            'phone_number': '9800000001', 'shipping_address': 'Kathmandu', 'payment_method': 'COD'})
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=2)
        self.manual = adjust_stock(self.variant, 5, 'ADJUSTMENT', user=self.owner,
                                   reference=self.order.order_number, note='Unrelated manual adjustment')
        self.order_activity = StaffActivity.objects.create(staff=self.staff, action='ORDER_STATUS',
                                                           reference=self.order.order_number, description='Processed')
        self.manual_activity = StaffActivity.objects.create(staff=self.owner, action='INVENTORY_ADJUSTMENT',
                                                            reference=self.order.order_number, description='Manual')
        self.order_log = LogEntry.objects.create(user=self.owner,
            content_type=ContentType.objects.get_for_model(Order), object_id=str(self.order.pk),
            object_repr=self.order.order_number, action_flag=CHANGE)
        self.product_log = LogEntry.objects.create(user=self.owner,
            content_type=ContentType.objects.get_for_model(Product), object_id=str(self.product.pk),
            object_repr=self.product.name, action_flag=CHANGE)
        self.apps = []
        for provider in ('google', 'facebook'):
            app = SocialApp.objects.create(provider=provider, name=provider, client_id='test', secret='test')
            self.apps.append(app)
            account = SocialAccount.objects.create(user=self.customer, provider=provider, uid=provider)
            SocialToken.objects.create(app=app, account=account, token='test')
        email = EmailAddress.objects.create(user=self.customer, email=self.customer.email, verified=True)
        EmailConfirmation.objects.create(email_address=email, key='test-key')
        self.protected_cart = Cart.objects.create(user=self.owner)
        CartItem.objects.create(cart=self.protected_cart, variant=self.variant, quantity=1)
        self.protected_order = create_order_from_cart(self.owner, self.protected_cart, {
            'first_name': 'Owner', 'last_name': 'Test', 'email': 'owner@example.com',
            'phone_number': '9800000002', 'shipping_address': 'Kathmandu', 'payment_method': 'COD'})
        CartItem.objects.create(cart=self.protected_cart, variant=self.variant, quantity=1)

    def run_command(self, confirm=False):
        output = StringIO()
        call_command('purge_customer_test_data', confirm=confirm, stdout=output)
        return output.getvalue()

    def snapshot(self):
        models = [User, Cart, CartItem, Order, OrderItem, InventoryTransaction, StaffActivity,
                  SocialApp, SocialAccount, SocialToken, EmailAddress, EmailConfirmation,
                  Product, ProductImage, ProductVariant, Category, Size, Color, LogEntry, Payment]
        return {model._meta.label: list(model.objects.order_by('pk').values()) for model in models}

    def test_dry_run_changes_nothing_and_previews_stock_and_counts(self):
        before = self.snapshot()
        output = self.run_command()
        self.assertEqual(before, self.snapshot())
        self.assertIn('DRY RUN', output)
        self.assertIn('PURGE-M (variant', output)
        self.assertIn('+3; 21 -> 24', output)
        self.assertIn('Protected OWNER/STAFF/admin users that will remain: 4', output)
        self.assertIn('Social tokens: 2', output)

    def test_confirm_removes_only_customer_data_restores_stock_and_is_idempotent(self):
        self.run_command(confirm=True)
        self.assertFalse(User.objects.filter(pk=self.customer.pk).exists())
        self.assertFalse(Cart.objects.filter(pk=self.cart.pk).exists())
        self.assertFalse(CartItem.objects.filter(cart_id=self.cart.pk).exists())
        self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())
        self.assertFalse(OrderItem.objects.filter(order_id=self.order.pk).exists())
        for model in (SocialAccount, SocialToken, EmailAddress, EmailConfirmation):
            self.assertFalse(model.objects.exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 24)
        self.assertFalse(InventoryTransaction.objects.filter(reference=self.order.order_number,
                                                             transaction_type='ORDER').exists())
        self.assertFalse(StaffActivity.objects.filter(pk=self.order_activity.pk).exists())
        self.assertTrue(StaffActivity.objects.filter(pk=self.manual_activity.pk).exists())
        self.assertFalse(LogEntry.objects.filter(pk=self.order_log.pk).exists())
        self.assertTrue(LogEntry.objects.filter(pk=self.product_log.pk).exists())
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.quantity, 5)
        for user in self.protected:
            user.refresh_from_db()
        self.assertEqual(User.objects.count(), 4)
        self.assertTrue(Order.objects.filter(pk=self.protected_order.pk).exists())
        self.assertEqual(CartItem.objects.filter(cart=self.protected_cart).count(), 1)
        for instance in [self.category, self.size, self.color, self.product, self.image, self.variant, *self.apps]:
            instance.refresh_from_db()
        self.assertEqual(self.product.price, 100)
        self.assertEqual(self.product.image.name, 'products/test.jpg')
        before = self.snapshot()
        self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_returns_are_not_restored_twice(self):
        adjust_stock(self.variant, 2, 'RETURN', user=self.staff, reference=self.order.order_number)
        self.run_command(confirm=True)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 24)
        self.assertFalse(InventoryTransaction.objects.filter(reference=self.order.order_number,
                                                             transaction_type='RETURN').exists())

    def test_missing_deduction_aborts_without_changes(self):
        InventoryTransaction.objects.filter(reference=self.order.order_number, transaction_type='ORDER').delete()
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'do not reconcile'):
            self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_missing_variant_aborts_without_changes(self):
        OrderItem.objects.filter(order=self.order).update(variant=None)
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'missing variant'):
            self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_protected_user_in_queryset_aborts(self):
        before = self.snapshot()
        with patch.object(Command, 'customer_queryset', return_value=User.objects.all()):
            with self.assertRaisesMessage(CommandError, 'Protected user included'):
                self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_deletion_failure_rolls_back_stock_and_all_cleanup(self):
        before = self.snapshot()
        with patch('accounts.management.commands.purge_customer_test_data.Collector.delete',
                   side_effect=RuntimeError('Deletion failed')):
            with self.assertRaisesMessage(RuntimeError, 'Deletion failed'):
                self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())


class OrphanedOrderCleanupTests(TransactionTestCase):
    setUp = PurgeCustomerTestDataTests.setUp
    snapshot = PurgeCustomerTestDataTests.snapshot

    @contextmanager
    def orphaned_order(self):
        # Model/schema correctly require a customer. Reproduce a legacy dangling
        # FK only in the isolated test DB, without changing models/migrations.
        with connection.constraint_checks_disabled():
            Order.objects.filter(pk=self.order.pk).update(customer_id=99999999)
            try:
                yield
            finally:
                Order.objects.filter(pk=self.order.pk).delete()

    def run_command(self, confirm=False, include_orphaned=True):
        output = StringIO()
        call_command('purge_customer_test_data', confirm=confirm,
                     include_orphaned=include_orphaned, stdout=output)
        return output.getvalue()

    def test_orphan_preview_changes_nothing_and_shows_protected_cart(self):
        with self.orphaned_order():
            before = self.snapshot()
            output = self.run_command()
            self.assertEqual(before, self.snapshot())
            self.assertIn(f'Orphaned order to delete: {self.order.order_number}', output)
            self.assertIn('Order item:', output)
            self.assertIn('Order inventory transaction:', output)
            self.assertIn('+3; 21 -> 24', output)
            self.assertIn(f'Protected cart that will remain: CART {self.protected_cart.pk}', output)

    def test_orphan_cleanup_restores_stock_and_preserves_protected_data(self):
        with self.orphaned_order():
            # Match the reported case with no ordinary customers or social data.
            self.customer.delete()
            self.run_command(confirm=True)
            self.assertFalse(Order.objects.filter(pk=self.order.pk).exists())
            self.assertFalse(OrderItem.objects.filter(order_id=self.order.pk).exists())
            self.variant.refresh_from_db()
            self.assertEqual(self.variant.stock_quantity, 24)
            self.assertFalse(InventoryTransaction.objects.filter(reference=self.order.order_number,
                                                                 transaction_type='ORDER').exists())
            for user in self.protected:
                user.refresh_from_db()
            self.protected_cart.refresh_from_db()
            self.assertEqual(self.protected_cart.user_id, self.owner.pk)
            self.assertEqual(CartItem.objects.filter(cart=self.protected_cart).count(), 1)
            self.protected_order.refresh_from_db()
            self.manual.refresh_from_db()
            self.assertEqual(self.manual.quantity, 5)
            self.manual_activity.refresh_from_db()
            for obj in [self.category, self.product, self.image, self.size, self.color, *self.apps]:
                obj.refresh_from_db()
            self.assertEqual(self.product.price, 100)
            before = self.snapshot()
            self.run_command(confirm=True)
            self.assertEqual(before, self.snapshot())

    def test_orphaned_orders_require_explicit_include_flag(self):
        with self.orphaned_order():
            self.run_command(confirm=True, include_orphaned=False)
            self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())
            self.variant.refresh_from_db()
            self.assertEqual(self.variant.stock_quantity, 21)

    def test_orphan_returns_reduce_stock_restoration(self):
        with self.orphaned_order():
            adjust_stock(self.variant, 2, 'RETURN', user=self.staff, reference=self.order.order_number)
            output = self.run_command(confirm=True)
            self.assertIn('+1; 23 -> 24', output)
            self.variant.refresh_from_db()
            self.assertEqual(self.variant.stock_quantity, 24)
            self.assertFalse(InventoryTransaction.objects.filter(reference=self.order.order_number,
                                                                 transaction_type='RETURN').exists())

    def test_orphan_inconsistent_inventory_aborts_all_cleanup(self):
        with self.orphaned_order():
            InventoryTransaction.objects.filter(reference=self.order.order_number,
                                                transaction_type='ORDER').delete()
            before = self.snapshot()
            with self.assertRaisesMessage(CommandError, 'do not reconcile'):
                self.run_command(confirm=True)
            self.assertEqual(before, self.snapshot())

    def test_orphan_excess_returns_abort_all_cleanup(self):
        with self.orphaned_order():
            adjust_stock(self.variant, 4, 'RETURN', user=self.staff, reference=self.order.order_number)
            before = self.snapshot()
            with self.assertRaisesMessage(CommandError, 'do not reconcile'):
                self.run_command(confirm=True)
            self.assertEqual(before, self.snapshot())


class ExplicitTestOrderCleanupTests(TestCase):
    snapshot = PurgeCustomerTestDataTests.snapshot

    def setUp(self):
        PurgeCustomerTestDataTests.setUp(self)
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        self.targets = []
        for number in TEST_ORDER_NUMBERS:
            # Use the actual checkout service so deductions reflect production.
            order = create_order_from_cart(self.owner, self.protected_cart, {
                'first_name': 'Owner', 'last_name': 'Test', 'email': 'owner@example.com',
                'phone_number': '9800000002', 'shipping_address': 'Kathmandu', 'payment_method': 'COD'})
            InventoryTransaction.objects.filter(reference=order.order_number).update(reference=number)
            order.order_number = number
            order.save(update_fields=['order_number'])
            self.targets.append(order)
            CartItem.objects.create(cart=self.protected_cart, variant=self.variant, quantity=1)
        self.matching_manual = adjust_stock(self.variant, 2, 'ADJUSTMENT', user=self.owner,
                                            reference=TEST_ORDER_NUMBERS[0])
        self.target_activity = StaffActivity.objects.create(staff=self.staff, action='PAYMENT_STATUS',
            reference=TEST_ORDER_NUMBERS[0], description='Test order payment')
        self.target_manual_activity = StaffActivity.objects.create(staff=self.owner, action='INVENTORY_ADJUSTMENT',
            reference=TEST_ORDER_NUMBERS[0], description='Unrelated manual inventory adjustment')
        self.target_log = LogEntry.objects.create(user=self.owner,
            content_type=ContentType.objects.get_for_model(Order), object_id=str(self.targets[0].pk),
            object_repr=TEST_ORDER_NUMBERS[0], action_flag=CHANGE)

    def run_command(self, confirm=False, **options):
        output = StringIO()
        call_command('purge_customer_test_data', purge_test_orders=True, confirm=confirm,
                     stdout=output, **options)
        return output.getvalue()

    def test_exact_mode_dry_run_previews_and_changes_nothing(self):
        before = self.snapshot()
        output = self.run_command()
        self.assertEqual(before, self.snapshot())
        for number in TEST_ORDER_NUMBERS:
            self.assertIn(f'Allowlisted test order to delete: {number}', output)
        self.assertIn('+5; 18 -> 23', output)
        self.assertIn('Activity to delete:', output)
        self.assertIn('Order inventory transaction:', output)
        self.assertIn(f'Protected cart that will remain: CART {self.protected_cart.pk}', output)
        self.assertIn('Protected user that will remain: owner', output)
        self.assertIn('CUSTOMER users: 0', output)

    def test_only_exact_orders_removed_and_all_users_carts_and_configuration_preserved(self):
        before = self.snapshot()
        self.run_command(confirm=True)
        self.assertFalse(Order.objects.filter(order_number__in=TEST_ORDER_NUMBERS).exists())
        self.assertFalse(OrderItem.objects.filter(order_id__in=[o.pk for o in self.targets]).exists())
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 23)
        self.assertEqual(set(Order.objects.values_list('pk', flat=True)), {self.order.pk, self.protected_order.pk})
        self.assertFalse(InventoryTransaction.objects.filter(reference__in=TEST_ORDER_NUMBERS,
                                                             transaction_type__in=['ORDER', 'RETURN']).exists())
        self.assertFalse(StaffActivity.objects.filter(pk=self.target_activity.pk).exists())
        self.assertFalse(LogEntry.objects.filter(pk=self.target_log.pk).exists())
        for entry in [self.manual, self.matching_manual, self.manual_activity, self.target_manual_activity]:
            entry.refresh_from_db()
        after = self.snapshot()
        for model in [User, Cart, CartItem, Product, ProductImage, Category, Size, Color,
                      SocialApp, SocialAccount, SocialToken, EmailAddress, EmailConfirmation]:
            self.assertEqual(before[model._meta.label], after[model._meta.label])
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_staff)
        self.assertTrue(self.owner.is_superuser)
        self.protected_cart.refresh_from_db()
        self.assertEqual(self.protected_cart.user_id, self.owner.pk)
        self.staff.refresh_from_db()
        self.run_command(confirm=True)
        self.assertEqual(after, self.snapshot())

    def test_recorded_returns_are_not_restored_twice(self):
        adjust_stock(self.variant, 1, 'RETURN', user=self.staff, reference=TEST_ORDER_NUMBERS[0])
        output = self.run_command(confirm=True)
        self.assertIn('+4; 19 -> 23', output)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 23)

    def test_inconsistent_target_history_aborts_everything(self):
        InventoryTransaction.objects.filter(reference=TEST_ORDER_NUMBERS[0], transaction_type='ORDER').delete()
        before = self.snapshot()
        with self.assertRaisesMessage(CommandError, 'do not reconcile'):
            self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_delete_failure_rolls_back_stock_and_target_history(self):
        before = self.snapshot()
        with patch('accounts.management.commands.purge_customer_test_data.Collector.delete',
                   side_effect=RuntimeError('Deletion failed')):
            with self.assertRaisesMessage(RuntimeError, 'Deletion failed'):
                self.run_command(confirm=True)
        self.assertEqual(before, self.snapshot())

    def test_exact_mode_cannot_be_combined_with_orphan_cleanup(self):
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.run_command(confirm=True, include_orphaned=True)
        self.assertEqual(before, self.snapshot())
