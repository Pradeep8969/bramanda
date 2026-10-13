from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from products.models import Category, Color, Product, ProductVariant, Size


class HomepageTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Essentials")
        self.color = Color.objects.create(name="Black")
        self.size = Size.objects.create(name="M")

    def product(self, index=0, **kwargs):
        return Product.objects.create(
            name=f"Essential {index}", category=self.category, price="845.00", **kwargs
        )

    def test_anonymous_homepage_editorial_sections_and_real_links(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for text in (
            "DEFINE YOUR",
            "OWN DIRECTION.",
            "Featured essentials",
            "THOUGHTFUL DESIGN",
            "EVERYDAY COMFORT",
            "DISTINCTIVE STYLE",
            "THE UNDISCOVERED",
            "home-perspective",
            "home-details",
            'id="about"',
        ):
            self.assertContains(response, text)
        self.assertContains(response, 'href="/shop/"')
        self.assertContains(response, 'href="/login/"')
        self.assertNotContains(response, "Free shipping")
        self.assertNotContains(response, "home-everyday")
        self.assertNotContains(response, "The everyday edit")
        self.assertNotContains(response, "EXPLORE THE COLLECTION")
        self.assertContains(response, "The Details<br>Matter")

    def test_luxury_split_uses_complete_brand_logo_and_static_artwork(self):
        response = self.client.get("/")
        self.assertContains(response, "/static/images/logo-beige-panel.png")
        self.assertContains(response, "/static/images/home/details-spiked-figure.webp")
        self.assertContains(response, "FIND YOUR DIRECTION")
        self.assertNotContains(response, "home-story-mark")
        self.assertNotContains(response, "data-details-slideshow")
        self.assertNotContains(response, "/static/js/home-details.js")
        self.assertNotContains(response, "EXPLORE THE COLLECTION")

    def test_dynamic_products_prices_images_and_stock(self):
        product = self.product(image="products/real.jpg")
        ProductVariant.objects.create(
            product=product,
            color=self.color,
            size=self.size,
            sku="HOME",
            stock_quantity=2,
        )
        response = self.client.get("/")
        self.assertContains(response, product.name)
        self.assertContains(response, "/media/products/real.jpg")
        self.assertContains(response, "Rs. 845.00")
        self.assertContains(response, "In Stock")
        link = reverse("products:detail", args=[product.slug])
        self.assertContains(response, f'href="{link}"')
        self.assertEqual(self.client.get(link).status_code, 200)

    def test_zero_through_four_products_are_unique_and_real(self):
        for count in range(5):
            response = self.client.get("/")
            products = response.context["featured_products"]
            self.assertEqual(len(products), count)
            self.assertEqual(len({p.pk for p in products}), count)
            self.assertContains(response, f'data-product-count="{count}"')
            if not count:
                self.assertContains(response, "Our next collection is taking shape.")
            self.product(count)

    def test_featured_priority_fills_remaining_slots_without_duplicates(self):
        first = self.product(0, featured=True)
        for index in range(1, 6):
            self.product(index)
        products = self.client.get("/").context["featured_products"]
        self.assertEqual(products[0].pk, first.pk)
        self.assertEqual(len(products), 4)
        self.assertEqual(len({p.pk for p in products}), 4)

    def test_inactive_products_and_categories_are_excluded(self):
        self.product(is_active=False)
        self.category.is_active = False
        self.category.save()
        self.product(1)
        self.assertEqual(self.client.get("/").context["featured_products"], [])

    def test_image_missing_uses_css_and_product_placeholder(self):
        self.product()
        with patch("bramanda.views.finders.find", return_value=None):
            response = self.client.get("/")
        self.assertNotContains(response, 'class="home-hero-photo"')
        self.assertContains(response, "Image coming soon")
        self.assertEqual(response.context["campaign_image"], "")

    def test_optional_campaign_image_has_priority_and_is_not_lazy(self):
        with patch(
            "bramanda.views.finders.find", return_value="approved-campaign.webp"
        ):
            response = self.client.get("/")
        self.assertContains(response, "/static/images/home/hero-editorial.webp")
        self.assertContains(response, 'fetchpriority="high"')
        self.assertContains(response, 'fetchpriority="high" width="1672" height="941"')

    def test_authenticated_navigation_cart_and_account_remain(self):
        user = User.objects.create_user(username="customer")
        self.client.force_login(user)
        response = self.client.get("/")
        for url in ("/profile/", "/orders/", "/cart/", "/logout/"):
            self.assertContains(response, url)
        self.assertContains(response, "Cart (0)")
        self.assertNotContains(response, "/accounts/facebook/")

    def test_home_css_does_not_load_on_other_pages(self):
        self.assertContains(self.client.get("/"), "/static/css/home.css")
        self.assertNotContains(self.client.get("/shop/"), "/static/css/home.css")

    def test_product_names_are_escaped(self):
        product = self.product()
        product.name = "<script>alert(1)</script>"
        product.save()
        response = self.client.get("/")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")
