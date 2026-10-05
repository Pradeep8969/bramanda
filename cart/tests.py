from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from products.models import Category, Color, Product, ProductVariant, Size
from .models import Cart, CartItem


class CartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='customer', password='Strong-Test-Password-845!')
        cls.other = get_user_model().objects.create_user(username='other')
        cls.category = Category.objects.create(name='T-Shirts')
        cls.black = Color.objects.create(name='Black')
        cls.beige = Color.objects.create(name='Beige')
        cls.medium = Size.objects.create(name='M')
        cls.large = Size.objects.create(name='L')
        cls.product = Product.objects.create(name='Bramanda Oversized T-Shirt', category=cls.category, price=Decimal('845.00'))
        cls.variant = ProductVariant.objects.create(product=cls.product, color=cls.black, size=cls.medium, sku='BLACK-M', stock_quantity=10)
        cls.second = ProductVariant.objects.create(product=cls.product, color=cls.beige, size=cls.large, sku='BEIGE-L', stock_quantity=5)

    def setUp(self):
        self.client.force_login(self.user)

    def add(self, quantity=1, variant=None, **extra):
        chosen = variant or self.variant
        data = {'variant': getattr(chosen, 'pk', chosen), 'quantity': quantity}
        data.update(extra)
        return self.client.post(reverse('cart:add', args=[self.product.slug]), data)

    def make_item(self, user=None, quantity=2):
        cart, _ = Cart.objects.get_or_create(user=user or self.user)
        return CartItem.objects.create(cart=cart, variant=self.variant, quantity=quantity)

    def test_cart_page_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get('/cart/'), '/login/?next=/cart/')

    def test_anonymous_add_returns_to_product_after_login(self):
        self.client.logout()
        response = self.add(2)
        self.assertEqual(response.status_code, 302)
        self.assertIn('next=/shop/bramanda-oversized-t-shirt/', response.url)
        response = self.client.post(response.url, {'username': 'customer', 'password': 'Strong-Test-Password-845!'})
        self.assertRedirects(response, '/shop/bramanda-oversized-t-shirt/')
        self.assertFalse(CartItem.objects.exists())

    def test_empty_cart(self):
        self.assertContains(self.client.get('/cart/'), 'Your cart is empty.')
        self.assertContains(self.client.get('/cart/'), 'Continue Shopping')
        self.assertFalse(Cart.objects.exists())

    def test_add_item_does_not_change_stock_or_trust_price(self):
        response = self.add(2, price='0.01', stock_quantity=999)
        self.assertRedirects(response, '/cart/')
        item = CartItem.objects.get()
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.unit_price, Decimal('845.00'))
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)

    def test_same_variant_increases_quantity(self):
        self.add(2)
        self.add(3)
        self.assertEqual(CartItem.objects.count(), 1)
        self.assertEqual(CartItem.objects.get().quantity, 5)

    def test_different_variants_create_different_items(self):
        self.add(2)
        self.add(1, self.second)
        self.assertEqual(CartItem.objects.count(), 2)
        self.assertEqual(Cart.objects.count(), 1)

    def test_invalid_quantities_are_rejected(self):
        for quantity in (0, -1, 11, 'abc', '1.5', '', 999999999999):
            with self.subTest(quantity=quantity):
                response = self.add(quantity)
                self.assertRedirects(response, '/shop/bramanda-oversized-t-shirt/')
                self.assertFalse(CartItem.objects.exists())

    def test_resulting_quantity_cannot_exceed_stock(self):
        self.add(8)
        response = self.add(3)
        self.assertEqual(CartItem.objects.get().quantity, 8)
        self.assertContains(self.client.get(response.url), 'including items already in your cart')

    def test_inactive_catalog_entries_cannot_be_added(self):
        for obj in (self.variant, self.product, self.category, self.black, self.medium):
            with self.subTest(model=type(obj).__name__):
                obj.is_active = False
                obj.save()
                response = self.add()
                self.assertIn(response.status_code, (302, 404))
                self.assertFalse(CartItem.objects.exists())
                obj.is_active = True
                obj.save()

    def test_out_of_stock_cannot_be_added(self):
        self.variant.stock_quantity = 0
        self.variant.save()
        self.add()
        self.assertFalse(CartItem.objects.exists())

    def test_variant_from_another_product_and_missing_ids_rejected(self):
        product = Product.objects.create(name='Another product', category=self.category, price=100)
        foreign_variant = ProductVariant.objects.create(product=product, color=self.black, size=self.medium, sku='FOREIGN', stock_quantity=10)
        self.add(variant=foreign_variant)
        self.add(variant=999999)
        self.assertFalse(CartItem.objects.exists())

    def test_update_quantity(self):
        item = self.make_item()
        response = self.client.post(reverse('cart:update', args=[item.pk]), {'quantity': 4})
        self.assertRedirects(response, '/cart/')
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 10)

    def test_update_rejects_invalid_or_excessive_quantity(self):
        item = self.make_item()
        for quantity in (0, -1, 11, 'bad', '1.5'):
            self.client.post(reverse('cart:update', args=[item.pk]), {'quantity': quantity})
            item.refresh_from_db()
            self.assertEqual(item.quantity, 2)

    def test_update_revalidates_catalog_activity(self):
        item = self.make_item()
        self.product.is_active = False
        self.product.save()
        self.client.post(reverse('cart:update', args=[item.pk]), {'quantity': 3})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
        self.assertContains(self.client.get('/cart/'), 'no longer available')

    def test_cart_warns_when_stock_falls_after_addition(self):
        self.make_item(quantity=5)
        self.variant.stock_quantity = 2
        self.variant.save()
        self.assertContains(self.client.get('/cart/'), 'Only 2 available')
        self.add(1)
        self.assertEqual(CartItem.objects.get().quantity, 5)

    def test_remove_item(self):
        item = self.make_item()
        self.assertRedirects(self.client.post(reverse('cart:remove', args=[item.pk])), '/cart/')
        self.assertFalse(CartItem.objects.exists())

    def test_customer_cannot_access_or_modify_another_cart(self):
        own = self.make_item()
        other_item = self.make_item(user=self.other, quantity=7)
        response = self.client.get('/cart/')
        self.assertEqual([i.pk for i in response.context['items']], [own.pk])
        for name in ('cart:update', 'cart:remove'):
            response = self.client.post(reverse(name, args=[other_item.pk]), {'quantity': 1})
            self.assertEqual(response.status_code, 404)
        other_item.refresh_from_db()
        self.assertEqual(other_item.quantity, 7)

    def test_model_totals_use_decimal_and_current_price(self):
        item = self.make_item(quantity=2)
        CartItem.objects.create(cart=item.cart, variant=self.second, quantity=3)
        self.assertEqual(item.unit_price, Decimal('845.00'))
        self.assertEqual(item.subtotal, Decimal('1690.00'))
        self.assertEqual(item.cart.total_items, 5)
        self.assertEqual(item.cart.subtotal, Decimal('4225.00'))
        self.product.price = Decimal('850.50')
        self.product.save()
        fresh = CartItem.objects.select_related('variant__product').get(pk=item.pk)
        self.assertEqual(fresh.subtotal, Decimal('1701.00'))
        empty = Cart.objects.create(user=self.other)
        self.assertEqual(empty.total_items, 0)
        self.assertEqual(empty.subtotal, Decimal('0.00'))
        self.assertIsInstance(empty.subtotal, Decimal)

    def test_cart_page_totals_and_navigation_counter(self):
        self.add(2)
        self.add(1, self.second)
        self.make_item(user=self.other, quantity=7)
        response = self.client.get('/cart/')
        self.assertContains(response, 'Cart (3)')
        self.assertContains(response, 'Rs. 2535.00')
        self.assertContains(response, 'Rs. 1690.00')
        self.assertContains(response, 'Black / M')
        self.assertContains(self.client.get('/shop/'), 'Cart (3)')

    def test_cart_constraints(self):
        item = self.make_item()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Cart.objects.create(user=self.user)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            CartItem.objects.create(cart=item.cart, variant=self.variant, quantity=1)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            CartItem.objects.filter(pk=item.pk).update(quantity=0)

    def test_all_mutations_are_post_only(self):
        item = self.make_item()
        urls = [reverse('cart:add', args=[self.product.slug]), reverse('cart:update', args=[item.pk]), reverse('cart:remove', args=[item.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_all_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        item = self.make_item()
        urls = [reverse('cart:add', args=[self.product.slug]), reverse('cart:update', args=[item.pk]), reverse('cart:remove', args=[item.pk]), '/logout/', '/profile/']
        for url in urls:
            self.assertEqual(client.post(url, {'quantity': 1, 'variant': self.variant.pk}).status_code, 403)

    def test_only_in_stock_active_product_variants_are_offered(self):
        self.second.stock_quantity = 0
        self.second.save()
        inactive = ProductVariant.objects.create(product=self.product, color=self.black, size=self.large, sku='INACTIVE', is_active=False, stock_quantity=3)
        response = self.client.get(reverse('products:detail', args=[self.product.slug]))
        offered = list(response.context['cart_form'].fields['variant'].queryset.values_list('pk', flat=True))
        self.assertEqual(offered, [self.variant.pk])
        self.assertNotIn(inactive.pk, offered)
        self.assertNotContains(response, f'<option value="{self.second.pk}">')

    def test_out_of_stock_product_disables_add_button(self):
        ProductVariant.objects.update(stock_quantity=0)
        response = self.client.get(reverse('products:detail', args=[self.product.slug]))
        self.assertContains(response, 'disabled aria-describedby="cart-note"')

