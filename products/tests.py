from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from inventory.models import InventoryTransaction
from .forms import ProductForm, ProductVariantForm
from .models import Category, Color, Product, ProductVariant, Size


class ProductTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='T-Shirts')
        self.product = Product.objects.create(name='Oversized T-Shirt', category=self.category, price=Decimal('845.00'))
        self.size = Size.objects.create(name='M', display_order=2)
        self.color = Color.objects.create(name='Black')

    def test_category_creation(self):
        self.assertEqual(self.category.slug, 't-shirts')
        self.assertEqual(str(self.category), 'T-Shirts')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Category.objects.create(name='T-Shirts')

    def test_product_creation_and_slug(self):
        self.assertEqual(self.product.price, Decimal('845.00'))
        self.assertEqual(self.product.slug, 'oversized-t-shirt')
        self.assertEqual(self.product.category, self.category)
        self.assertNotIn('stock_quantity', [field.name for field in Product._meta.fields])
        self.product.name = 'Renamed Shirt'
        self.product.save()
        self.assertEqual(self.product.slug, 'oversized-t-shirt')

    def test_slug_collision(self):
        second = Product.objects.create(name=self.product.name, category=self.category, price=1)
        self.assertEqual(second.slug, 'oversized-t-shirt-2')

    def test_negative_price_rejected(self):
        self.product.price = Decimal('-1.00')
        with self.assertRaises(ValidationError):
            self.product.full_clean()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Product.objects.filter(pk=self.product.pk).update(price=-1)

    def make_variant(self, **kwargs):
        return ProductVariant.objects.create(product=self.product, size=self.size, color=self.color, **kwargs)

    def test_unique_variant_combination(self):
        self.make_variant(sku='FIRST')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self.make_variant(sku='SECOND')

    def test_unique_sku(self):
        self.make_variant(sku='SAME')
        other_size = Size.objects.create(name='L')
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ProductVariant.objects.create(product=self.product, size=other_size, color=self.color, sku='SAME')

    def test_negative_stock_rejected(self):
        variant = ProductVariant(product=self.product, size=self.size, color=self.color, sku='NEG', stock_quantity=-1)
        with self.assertRaises(ValidationError):
            variant.full_clean()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            variant.save()

    def test_in_stock(self):
        variant = self.make_variant(sku='STOCK')
        self.assertFalse(variant.in_stock)
        variant.stock_quantity = 1
        self.assertTrue(variant.in_stock)

    def test_forms(self):
        form = ProductForm(data={'name': 'New Shirt', 'category': self.category.pk, 'price': '20.00', 'is_active': True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().slug, 'new-shirt')
        self.assertNotIn('stock_quantity', ProductVariantForm().fields)

    def test_seed_is_reusable_and_preserves_stock(self):
        call_command('seed_bramanda', stdout=StringIO())
        product = Product.objects.get(slug='bramanda-oversized-t-shirt')
        self.assertEqual(product.price, Decimal('845.00'))
        self.assertEqual(product.variants.count(), 12)
        self.assertEqual(InventoryTransaction.objects.count(), 12)
        before = list(product.variants.values_list('sku', 'stock_quantity'))
        call_command('seed_bramanda', stdout=StringIO())
        self.assertEqual(list(product.variants.values_list('sku', 'stock_quantity')), before)
        self.assertEqual(InventoryTransaction.objects.count(), 12)
