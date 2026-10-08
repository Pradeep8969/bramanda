from pathlib import Path
import shutil
import subprocess
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from cart.models import CartItem
from .models import Category, Color, Product, ProductVariant, Size


class VariantSelectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(name='Selector Shirt', category=Category.objects.create(name='Shirts'), price=500)
        small = Size.objects.create(name='S')
        medium = Size.objects.create(name='M')
        black = Color.objects.create(name='Black', hex_code='#000000')
        beige = Color.objects.create(name='Beige', hex_code='#eee8dc')
        red = Color.objects.create(name='Red', hex_code='#ff0000')
        cls.black_small = ProductVariant.objects.create(product=cls.product, color=black, size=small, sku='BLACK-S', stock_quantity=3)
        cls.black_medium = ProductVariant.objects.create(product=cls.product, color=black, size=medium, sku='BLACK-M', stock_quantity=0)
        cls.beige_medium = ProductVariant.objects.create(product=cls.product, color=beige, size=medium, sku='BEIGE-M', stock_quantity=4)
        ProductVariant.objects.create(product=cls.product, color=red, size=small, sku='RED-S', stock_quantity=0)
        cls.customer = get_user_model().objects.create_user(username='selector-buyer')

    def detail(self):
        return self.client.get(reverse('products:detail', args=[self.product.slug]))

    def colors(self):
        return {color['name']: color for color in self.detail().context['color_options']}

    def test_colors_and_sizes_use_each_variants_actual_stock(self):
        colors = self.colors()
        self.assertTrue(colors['Black']['available'])
        self.assertFalse(colors['Red']['available'])
        self.assertEqual([(size['name'], size['stock']) for size in colors['Black']['sizes']], [('M', 0), ('S', 3)])
        self.assertEqual([(size['name'], size['stock']) for size in colors['Beige']['sizes']], [('M', 4)])
        self.assertEqual(colors['Black']['hex_code'], '#000000')
        response = self.detail()
        self.assertContains(response, 'disabled title="Red — Sold Out"')
        self.assertNotContains(response, 'availability-details')
        self.assertNotContains(response, '<table')

    def test_entire_product_sold_out_disables_cart(self):
        ProductVariant.objects.filter(product=self.product).update(stock_quantity=0)
        self.assertTrue(all(not color['available'] for color in self.colors().values()))
        self.assertContains(self.detail(), 'disabled aria-describedby="cart-note"')
        self.assertContains(self.detail(), 'Sold Out')

    def test_sold_out_size_cannot_borrow_stock_from_another_color(self):
        self.client.force_login(self.customer)
        self.client.post(reverse('cart:add', args=[self.product.slug]), {'variant': self.black_medium.pk, 'quantity': 1})
        self.assertFalse(CartItem.objects.exists())
        self.client.post(reverse('cart:add', args=[self.product.slug]), {'variant': self.beige_medium.pk, 'quantity': 4})
        self.assertEqual(CartItem.objects.get().variant_id, self.beige_medium.pk)

    def test_owner_and_staff_stock_updates_reflect_on_storefront_and_reject_stale_selection(self):
        for role, portal in [('OWNER', 'owner'), ('STAFF', 'staff')]:
            with self.subTest(role=role):
                user = get_user_model().objects.create_user(username=portal, role=role)
                self.client.force_login(user)
                self.assertEqual(self.client.post(f'/{portal}/inventory/adjust/', {
                    'variant': self.black_small.pk, 'quantity_change': -3, 'note': 'Stock update',
                }).status_code, 302)
                self.assertFalse(self.colors()['Black']['available'])
                self.beige_medium.refresh_from_db()
                self.assertEqual(self.beige_medium.stock_quantity, 4)
                self.client.force_login(self.customer)
                self.client.post(reverse('cart:add', args=[self.product.slug]), {'variant': self.black_small.pk, 'quantity': 1})
                self.assertFalse(CartItem.objects.exists())
                self.client.force_login(user)
                self.assertEqual(self.client.post(f'/{portal}/inventory/adjust/', {
                    'variant': self.black_small.pk, 'quantity_change': 3, 'note': 'Restock',
                }).status_code, 302)
                self.assertTrue(self.colors()['Black']['available'])

    def test_customer_cannot_change_inventory(self):
        self.client.force_login(self.customer)
        for portal in ('owner', 'staff'):
            self.assertEqual(self.client.post(f'/{portal}/inventory/adjust/', {
                'variant': self.black_small.pk, 'quantity_change': 10, 'note': 'Unauthorized',
            }).status_code, 403)
        self.black_small.refresh_from_db()
        self.assertEqual(self.black_small.stock_quantity, 3)


class SelectionJavaScriptTests(SimpleTestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for selector JavaScript tests')
    def test_color_changes_and_disabled_options(self):
        result = subprocess.run(
            [shutil.which('node'), '--test', str(Path(settings.BASE_DIR) / 'products/tests_js/product_selection.test.js')],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
