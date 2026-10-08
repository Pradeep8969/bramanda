from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Category, Color, Product, ProductImage, ProductVariant, Size


class StorefrontTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='T-Shirts')
        cls.other_category = Category.objects.create(name='Hoodies')
        cls.small = Size.objects.create(name='S', display_order=1)
        cls.medium = Size.objects.create(name='M', display_order=2)
        cls.black = Color.objects.create(name='Black')
        cls.beige = Color.objects.create(name='Beige')
        cls.shirt = Product.objects.create(name='Alpha Shirt', category=cls.category, price=100, description='Soft cotton essential', featured=True)
        cls.hoodie = Product.objects.create(name='Beta Hoodie', category=cls.other_category, price=200)
        cls.inactive = Product.objects.create(name='Hidden Product', category=cls.category, price=50, is_active=False, featured=True)
        cls.variant = ProductVariant.objects.create(product=cls.shirt, size=cls.small, color=cls.black, sku='PRIVATE-SKU', stock_quantity=10)
        ProductVariant.objects.create(product=cls.shirt, size=cls.medium, color=cls.beige, sku='BEIGE-M', stock_quantity=0)
        ProductVariant.objects.create(product=cls.hoodie, size=cls.medium, color=cls.black, sku='HOODIE-M', stock_quantity=0)

    def shop(self, **params):
        return self.client.get(reverse('products:shop'), params)

    def names(self, response):
        return [p.name for p in response.context['products']]

    def detail(self, product=None):
        return self.client.get(reverse('products:detail', args=[(product or self.shirt).slug]))

    def test_shop_loads_and_only_active_products_appear(self):
        response = self.shop()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.shirt.name)
        self.assertNotContains(response, self.inactive.name)
        self.assertContains(response, 'Image coming soon')

    def test_detail_and_safe_variant_data(self):
        response = self.detail()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '10 available')
        self.assertContains(response, 'Beige — Sold Out')
        self.assertNotContains(response, 'PRIVATE-SKU')
        self.assertContains(response, 'class="variant-selector"')
        colors = {color['name']: color for color in response.context['color_options']}
        self.assertFalse(colors['Beige']['available'])
        self.assertTrue(colors['Black']['available'])
        self.assertEqual(colors['Black']['sizes'], [{'name': 'S', 'stock': 10, 'variant_id': self.variant.pk}])
        self.assertNotContains(response, 'availability-details')

    def test_inactive_and_missing_detail_return_404(self):
        self.assertEqual(self.detail(self.inactive).status_code, 404)
        self.assertEqual(self.client.get('/shop/missing-product/').status_code, 404)

    def test_search_name_description_and_category(self):
        for query in ('alpha', 'cotton', 't-shirts'):
            with self.subTest(query=query):
                response = self.shop(q=query)
                self.assertEqual(self.names(response), [self.shirt.name])
                self.assertContains(response, f'value="{query}"')

    def test_empty_search(self):
        self.assertContains(self.shop(q='nothing-matches'), 'No products found')

    def test_category_filter(self):
        self.assertEqual(self.names(self.shop(category='hoodies')), [self.hoodie.name])

    def test_color_filter(self):
        self.assertEqual(self.names(self.shop(color='Beige')), [self.shirt.name])

    def test_size_filter(self):
        self.assertEqual(self.names(self.shop(size='S')), [self.shirt.name])

    def test_filters_combine_on_same_variant(self):
        self.assertEqual(self.names(self.shop(q='cotton', category='t-shirts', color='Black', size='S')), [self.shirt.name])
        self.assertEqual(self.names(self.shop(category='t-shirts', color='Black', size='M')), [])

    def test_variant_joins_do_not_duplicate_products(self):
        ProductVariant.objects.create(product=self.shirt, size=self.medium, color=self.black, sku='BLACK-M', stock_quantity=2)
        self.assertEqual(self.names(self.shop(color='Black')).count(self.shirt.name), 1)

    def test_sorting_and_invalid_sort_fallback(self):
        expected = {'newest': [self.hoodie.name, self.shirt.name], 'price_asc': [self.shirt.name, self.hoodie.name],
                    'price_desc': [self.hoodie.name, self.shirt.name], 'name': [self.shirt.name, self.hoodie.name]}
        for sort, names in expected.items():
            with self.subTest(sort=sort):
                self.assertEqual(self.names(self.shop(sort=sort)), names)
        self.assertEqual(self.names(self.shop(sort='invalid')), expected['newest'])

    def test_out_of_stock_uses_active_variants(self):
        response = self.shop()
        self.assertContains(response, 'In Stock')
        self.assertContains(response, 'Out of Stock')
        self.variant.is_active = False
        self.variant.save()
        self.assertContains(self.detail(), 'Sold Out')
        self.assertNotContains(self.detail(), '10 available')
        self.assertEqual(self.names(self.shop(size='S')), [])

    def test_inactive_sizes_and_colors_are_hidden(self):
        for attribute in (self.small, self.black):
            attribute.is_active = False
            attribute.save()
        response = self.shop()
        self.assertNotContains(response, '<option value="Black"')
        self.assertNotContains(response, '<option value="S"')
        self.assertEqual(self.names(self.shop(color='Black')), [])
        self.assertEqual(self.names(self.shop(size='S')), [])
        self.assertNotIn('Black', [color['name'] for color in self.detail().context['color_options']])
        self.assertContains(self.detail(), 'Sold Out')

    def test_inactive_category_is_hidden(self):
        self.category.is_active = False
        self.category.save()
        self.assertNotContains(self.shop(), self.shirt.name)
        self.assertNotContains(self.shop(), '<option value="t-shirts"')
        self.assertEqual(self.detail().status_code, 404)

    def test_homepage_featured_products(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.shirt.name)
        self.assertNotContains(response, self.hoodie.name)
        self.assertNotContains(response, self.inactive.name)

    def test_homepage_falls_back_to_active_products(self):
        Product.objects.update(featured=False)
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.shirt.name)
        self.assertContains(response, self.hoodie.name)
        self.assertNotContains(response, self.inactive.name)

    def test_homepage_empty_catalog(self):
        Product.objects.update(is_active=False)
        self.assertContains(self.client.get(reverse('home')), 'Our next collection is taking shape')

    def test_images_and_gallery(self):
        self.shirt.image = 'products/shirt.jpg'
        self.shirt.save()
        ProductImage.objects.create(product=self.shirt, image='products/gallery/back.jpg', alt_text='Back view')
        self.assertContains(self.shop(), '/media/products/shirt.jpg')
        self.assertContains(self.detail(), '/media/products/gallery/back.jpg')
        self.assertContains(self.detail(), 'alt="Back view"')

    def test_authenticated_navigation(self):
        user = get_user_model().objects.create_user(username='shopper')
        self.client.force_login(user)
        response = self.shop()
        for label in ('My Orders', 'Profile', 'Logout'):
            self.assertContains(response, label)
        self.assertNotContains(response, '>Login<')

    def test_product_prefetch_query_count_does_not_grow(self):
        # The catalog and its active variants are fetched in two queries.
        from .views import prepare_products, storefront_products
        with self.assertNumQueries(2):
            products = prepare_products(list(storefront_products()))
            for product in products:
                str(product.category)
                for variant in product.storefront_variants:
                    str(variant.size)
                    str(variant.color)
