from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from products.models import Category, Color, Product, ProductVariant, Size
from .models import InventoryTransaction
from .services import adjust_stock


class InventoryTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name='Shirts')
        product = Product.objects.create(name='Shirt', category=category, price=100)
        self.variant = ProductVariant.objects.create(
            product=product, size=Size.objects.create(name='M'),
            color=Color.objects.create(name='Black'), sku='TEST', stock_quantity=10,
        )
        self.user = get_user_model().objects.create_user(username='owner', role='OWNER')

    def test_stock_increase_and_transaction(self):
        record = adjust_stock(self.variant, 5, 'STOCK_IN', self.user, 'REF-1', 'Delivery')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 15)
        self.assertEqual((record.previous_stock, record.quantity, record.new_stock), (10, 5, 15))
        self.assertEqual(record.created_by, self.user)
        self.assertEqual(record.reference, 'REF-1')
        self.assertEqual(record.note, 'Delivery')
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def test_stock_decrease(self):
        record = adjust_stock(self.variant, -4, 'STOCK_OUT')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 6)
        self.assertEqual(record.new_stock, 6)

    def test_cannot_go_below_zero(self):
        with self.assertRaises(ValidationError):
            adjust_stock(self.variant, -11, 'STOCK_OUT')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_can_reach_zero(self):
        adjust_stock(self.variant, -10, 'STOCK_OUT')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 0)

    def test_invalid_inputs_leave_stock_unchanged(self):
        for quantity, kind in ((1, 'INVALID'), (0, 'ADJUSTMENT'), (1.5, 'ADJUSTMENT'),
                               (True, 'STOCK_IN'), (-1, 'RETURN'), (1, 'ORDER')):
            with self.subTest(quantity=quantity, kind=kind), self.assertRaises(ValidationError):
                adjust_stock(self.variant, quantity, kind)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_stale_instance_uses_current_database_stock(self):
        adjust_stock(self.variant, 5, 'STOCK_IN')
        record = adjust_stock(self.variant, -2, 'ADJUSTMENT')
        self.assertEqual((record.previous_stock, record.new_stock), (15, 13))

    def test_stock_rolls_back_if_history_save_fails(self):
        with patch.object(InventoryTransaction, 'save', side_effect=RuntimeError('Save failed')):
            with self.assertRaises(RuntimeError):
                adjust_stock(self.variant, 5, 'STOCK_IN')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_creating_history_does_not_change_stock(self):
        InventoryTransaction.objects.create(variant=self.variant, transaction_type='ADJUSTMENT',
                                            quantity=2, previous_stock=10, new_stock=12)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)
