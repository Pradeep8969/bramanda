from decimal import Decimal

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.test import Client, TestCase
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.models import User
from accounts.views import profile_context
from orders.models import Order, OrderItem
from products.models import Category, Product, ProductImage


class ProfilePresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="alexshrestha",
            first_name="Alex",
            last_name="Shrestha",
            email="alex@example.com",
            phone_number="9811111111",
            address="Kathmandu",
        )
        cls.other = User.objects.create_user(
            username="another", email="other@example.com"
        )
        cls.product = Product.objects.create(
            name="Oversized T-Shirt",
            category=Category.objects.create(name="Essentials"),
            price=Decimal("845.00"),
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("accounts:profile")

    def verify_email(self, email=None, user=None, verified=True):
        return EmailAddress.objects.create(
            user=user or self.user, email=email or self.user.email, verified=verified
        )

    def data(self, **changes):
        data = {field: getattr(self.user, field) for field in ProfileForm.Meta.fields}
        data.update(changes)
        return data

    def order(self, customer=None, status="CONFIRMED", total="945.00", product=None):
        order = Order.objects.create(
            customer=customer or self.user,
            first_name="Alex",
            last_name="Shrestha",
            email="alex@example.com",
            phone_number="9811111111",
            shipping_address="Kathmandu",
            subtotal=Decimal(total) - 100,
            shipping_cost=100,
            grand_total=total,
            order_status=status,
        )
        OrderItem.objects.create(
            order=order,
            product=product or self.product,
            product_name="Oversized T-Shirt",
            size_name="M",
            color_name="Black",
            sku="PROFILE-ITEM",
            quantity=1,
            unit_price=845,
            subtotal=845,
        )
        return order

    def test_authenticated_profile_keeps_existing_layout_and_private_fields(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/profile.html")
        for text in (
            "My profile",
            "Account details",
            "Profile completion",
            "Recent order",
            "BRAMANDA member",
            "account-layout",
            "Save Changes",
            "alexshrestha",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "Continue with Facebook")
        self.assertNotContains(response, 'name="username"')

    def test_anonymous_cannot_view_profile(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, "/login/?next=/profile/")
        self.assertNotIn(b"alex@example.com", response.content)

    def test_initials_and_full_name_come_from_customer(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["profile_initials"], "AS")
        self.assertEqual(response.context["profile_name"], "Alex Shrestha")

    def test_missing_names_fall_back_to_username(self):
        User.objects.filter(pk=self.user.pk).update(first_name="", last_name="")
        response = self.client.get(self.url)
        self.assertEqual(response.context["profile_initials"], "AL")
        self.assertEqual(response.context["profile_name"], self.user.username)

    def test_generic_initial_and_single_name_fallback(self):
        user = User(username="", first_name="", last_name="")
        # A saved instance is required only for the read-only related queries.
        user.pk = self.user.pk
        context = profile_context(user, ProfileForm(instance=user))
        self.assertEqual(context["profile_initials"], "B")
        user.first_name = "Asha"
        self.assertEqual(
            profile_context(user, ProfileForm(instance=user))["profile_initials"], "A"
        )

    def test_unverified_email_does_not_count_as_complete_or_show_badge(self):
        self.verify_email(verified=False)
        response = self.client.get(self.url)
        self.assertEqual(response.context["profile_completion"], 80)
        self.assertEqual(
            response.context["completion_hint"], "Your email is not yet verified."
        )
        self.assertFalse(response.context["email_verified"])
        self.assertNotContains(response, "profile-email")

    def test_verified_matching_email_case_insensitive(self):
        self.verify_email(email="ALEX@example.com")
        response = self.client.get(self.url)
        self.assertTrue(response.context["email_verified"])
        self.assertContains(response, "profile-email")
        self.assertContains(response, "Verified")
        self.assertEqual(response.context["profile_completion"], 100)
        self.assertEqual(
            response.context["completion_hint"], "Your profile is complete."
        )

    def test_mismatched_verified_email_does_not_show_badge(self):
        self.verify_email(email="old@example.com")
        self.assertFalse(self.client.get(self.url).context["email_verified"])

    def test_another_users_verified_email_does_not_verify_current_user(self):
        self.verify_email(user=self.other, email=self.user.email)
        self.assertFalse(self.client.get(self.url).context["email_verified"])

    def test_missing_fields_have_real_percentage_and_helpful_hints(self):
        self.verify_email()
        for field, hint in [
            ("first_name", "first name"),
            ("last_name", "last name"),
            ("phone_number", "phone number"),
            ("address", "address"),
        ]:
            with self.subTest(field=field):
                original = getattr(self.user, field)
                User.objects.filter(pk=self.user.pk).update(**{field: "   "})
                response = self.client.get(self.url)
                self.assertEqual(response.context["profile_completion"], 80)
                self.assertIn(hint, response.context["completion_hint"])
                User.objects.filter(pk=self.user.pk).update(**{field: original})
        User.objects.filter(pk=self.user.pk).update(email="")
        response = self.client.get(self.url)
        self.assertEqual(response.context["profile_completion"], 80)
        self.assertIn("Add your email address", response.context["completion_hint"])

    def test_empty_profile_completion_is_zero(self):
        User.objects.filter(pk=self.user.pk).update(
            first_name="", last_name="", email="", phone_number="", address=""
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["profile_completion"], 0)

    def test_completion_updates_after_save_and_success_message_is_consumed(self):
        self.verify_email()
        User.objects.filter(pk=self.user.pk).update(phone_number="")
        self.assertEqual(self.client.get(self.url).context["profile_completion"], 80)
        response = self.client.post(
            self.url, self.data(phone_number="9811111111"), follow=True
        )
        self.assertRedirects(response, self.url)
        self.assertEqual(response.context["profile_completion"], 100)
        self.assertContains(response, "Your profile has been updated.", count=1)
        self.assertContains(response, 'data-auto-dismiss="5000"', count=1)
        self.assertEqual(len(list(response.context["messages"])), 1)
        self.assertNotContains(
            self.client.get(self.url), "Your profile has been updated."
        )

    def test_email_change_never_inherits_previous_verification(self):
        record = self.verify_email()
        response = self.client.post(
            self.url, self.data(email="new@example.com"), follow=True
        )
        self.assertFalse(response.context["email_verified"])
        self.assertEqual(response.context["profile_completion"], 80)
        record.refresh_from_db()
        self.assertEqual(record.email, "alex@example.com")
        self.assertFalse(
            EmailAddress.objects.filter(
                user=self.user, email="new@example.com", verified=True
            ).exists()
        )

    def test_google_badge_requires_current_users_google_record(self):
        SocialAccount.objects.create(
            user=self.other, provider="google", uid="other-google"
        )
        SocialAccount.objects.create(
            user=self.user, provider="facebook", uid="legacy-only"
        )
        self.assertNotContains(self.client.get(self.url), "Google linked")
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="current-google"
        )
        self.assertContains(self.client.get(self.url), "Google linked")

    def test_invalid_form_preserves_saved_data_and_entered_values_without_verified_badge(
        self,
    ):
        self.verify_email()
        response = self.client.post(
            self.url,
            self.data(first_name="Edited", email="not-an-email", address="New address"),
        )
        self.assertIn("email", response.context["form"].errors)
        self.assertContains(response, 'value="Edited"')
        self.assertContains(response, "not-an-email")
        self.assertContains(response, "New address")
        self.assertFalse(response.context["email_verified"])
        self.assertEqual(response.context["profile_name"], "Alex Shrestha")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alex")
        self.assertEqual(self.user.address, "Kathmandu")
        self.assertEqual(self.user.email, "alex@example.com")

    def test_csrf_and_readonly_fields_preserved(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url, self.data()).status_code, 403)
        self.client.post(self.url, self.data(username="changed", role="OWNER"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alexshrestha")
        self.assertEqual(self.user.role, "CUSTOMER")

    def test_recent_order_is_latest_owned_order_with_real_total_status_and_links(self):
        self.order()
        latest = self.order(status="CANCELLED", total="1790.00")
        other_order = self.order(customer=self.other, status="DELIVERED")
        response = self.client.get(self.url)
        self.assertEqual(response.context["recent_order"].pk, latest.pk)
        self.assertContains(response, latest.order_number)
        self.assertContains(response, "Oversized T-Shirt")
        self.assertContains(response, "Rs. 1790.00")
        self.assertContains(response, "Cancelled")
        self.assertNotContains(response, other_order.order_number)
        for url in (
            reverse("orders:list"),
            reverse("orders:detail", args=[latest.order_number]),
        ):
            self.assertContains(response, f'href="{url}"')
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_orders_has_empty_state_and_other_customer_order_is_private(self):
        other_order = self.order(customer=self.other)
        response = self.client.get(self.url)
        self.assertContains(response, "You haven't placed an order yet.")
        self.assertIsNone(response.context["recent_order"])
        self.assertNotContains(response, other_order.order_number)

    def test_order_image_and_gallery_fallback(self):
        self.product.image = "products/example.jpg"
        self.product.save()
        self.order()
        self.assertContains(self.client.get(self.url), "/media/products/example.jpg")
        self.product.image = ""
        self.product.save()
        ProductImage.objects.create(
            product=self.product, image="products/gallery/example.jpg"
        )
        self.assertContains(
            self.client.get(self.url), "/media/products/gallery/example.jpg"
        )

    def test_missing_deleted_product_or_empty_order_has_placeholder(self):
        order = self.order()
        order.items.update(product=None)
        response = self.client.get(self.url)
        self.assertIsNone(response.context["recent_image"])
        self.assertContains(response, "Oversized T-Shirt")
        order.items.all().delete()
        self.assertContains(self.client.get(self.url), "Order details")

    def test_customer_and_order_text_is_escaped(self):
        User.objects.filter(pk=self.user.pk).update(
            first_name="<script>alert(1)</script>"
        )
        order = self.order()
        order.items.update(product_name="<img src=x onerror=alert(1)>")
        response = self.client.get(self.url)
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "&lt;img")

    def test_preview_queries_are_bounded_regardless_of_order_item_count(self):
        order = self.order()
        for index in range(10):
            OrderItem.objects.create(
                order=order,
                product=self.product,
                product_name="Additional item",
                size_name="M",
                color_name="Black",
                sku=f"EXTRA-{index}",
                quantity=1,
                unit_price=845,
                subtotal=845,
            )
        with self.assertNumQueries(5):
            context = profile_context(self.user, ProfileForm(instance=self.user))
            self.assertEqual(context["recent_item"].product_name, "Oversized T-Shirt")
