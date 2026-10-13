from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order, OrderItem

from .invoice_links import MAX_AGE, invoice_identity, invoice_url, signer


@override_settings(
    INVOICE_SIGNING_KEY="test-private-invoice-signing-key-at-least-32-characters",
    BRAMANDA_PUBLIC_BASE_URL="http://127.0.0.1:8000",
)
class SignedInvoiceTests(TestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username="invoice-customer"
        )
        self.other = get_user_model().objects.create_user(username="invoice-other")
        self.order = Order.objects.create(
            customer=self.customer,
            first_name="Asha",
            last_name="Rai",
            email="invoice@example.com",
            phone_number="9800000000",
            shipping_address="Pokhara",
            subtotal=500,
            shipping_cost=100,
            grand_total=600,
        )
        self.other_order = Order.objects.create(
            customer=self.other,
            first_name="Different",
            last_name="Buyer",
            email="other@example.com",
            shipping_address="Kathmandu",
            subtotal=20,
            shipping_cost=100,
            grand_total=120,
        )
        OrderItem.objects.create(
            order=self.order,
            product_name="Invoice Shirt",
            size_name="M",
            color_name="Black",
            sku="INV",
            quantity=2,
            unit_price=250,
            subtotal=500,
        )

    def path(self):
        return urlsplit(invoice_url(self.order)).path

    def test_valid_link_opens_correct_invoice_for_guest_without_login(self):
        response = self.client.get(self.path())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "payments/document.html")
        for text in (
            self.order.order_number,
            "Asha",
            "Invoice Shirt",
            "Pokhara",
            "600.00",
            "Print / Save as PDF",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, self.other_order.order_number)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")

    def test_valid_link_is_bearer_access_even_when_another_customer_is_logged_in(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.path()).status_code, 200)

    def test_invoice_details_and_friendly_payment_status_for_cod_and_esewa(self):
        for method, status, label in (
            ("COD", "UNPAID", "Payment Remaining"),
            ("COD", "PAID", "Paid"),
            ("ESEWA", "PAID", "Paid"),
        ):
            with self.subTest(method=method, status=status):
                self.order.payment_method = method
                self.order.payment_status = status
                self.order.save(update_fields=["payment_method", "payment_status"])
                response = self.client.get(self.path())
                for text in (
                    self.order.order_number,
                    "Order date",
                    "Invoice Shirt",
                    "250.00",
                    "500.00",
                    "100.00",
                    "600.00",
                    "Subtotal",
                    "Shipping",
                    "Grand total",
                    "Pokhara",
                    self.order.get_payment_method_display(),
                    label,
                    "Print / Save as PDF",
                    'onclick="window.print()"',
                ):
                    self.assertContains(response, text)
                self.assertContains(response, "&times; 2")

    def test_expiry_seven_days(self):
        with patch("django.core.signing.time.time", return_value=1000000000):
            path = self.path()
        with patch("django.core.signing.time.time", return_value=1000000000 + MAX_AGE):
            self.assertEqual(self.client.get(path).status_code, 200)
        with patch(
            "django.core.signing.time.time", return_value=1000000000 + MAX_AGE + 1
        ):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_tampered_signature_payload_and_timestamp_rejected(self):
        token = self.path().rstrip("/").rsplit("/", 1)[1]
        parts = token.split(":")
        for index in range(3):
            altered = list(parts)
            altered[index] = ("A" if altered[index][0] != "A" else "B") + altered[
                index
            ][1:]
            path = reverse("payments:signed_invoice", args=[":".join(altered)])
            self.assertEqual(self.client.get(path).status_code, 404)
        for token in ("invalid", self.order.order_number):
            self.assertEqual(
                self.client.get(
                    reverse("payments:signed_invoice", args=[token])
                ).status_code,
                404,
            )

    def test_customer_and_order_identity_must_match(self):
        token = signer().sign_object(
            {
                "order": self.other_order.pk,
                "customer": self.customer.pk,
                "number": self.order.order_number,
            }
        )
        self.assertEqual(
            self.client.get(
                reverse("payments:signed_invoice", args=[token])
            ).status_code,
            404,
        )
        url = self.path()
        self.order.customer = self.other
        self.order.save(update_fields=["customer"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_malformed_signed_identity_rejected(self):
        for data in (
            {},
            {
                "order": str(self.order.pk),
                "customer": self.customer.pk,
                "number": self.order.order_number,
            },
            ["invalid"],
        ):
            token = signer().sign_object(data)
            self.assertEqual(
                self.client.get(
                    reverse("payments:signed_invoice", args=[token])
                ).status_code,
                404,
            )

    def test_existing_invoice_permissions_preserved(self):
        path = reverse("payments:invoice", args=[self.order.order_number])
        self.assertEqual(self.client.get(path).status_code, 302)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(path).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(path).status_code, 404)
        for role in ("OWNER", "STAFF"):
            user = get_user_model().objects.create_user(
                username=role.lower() + "-invoice", role=role
            )
            self.client.force_login(user)
            self.assertEqual(self.client.get(path).status_code, 200)

    @override_settings(BRAMANDA_PUBLIC_BASE_URL="https://bramanda.example")
    def test_email_origin_uses_bramanda_setting(self):
        url = invoice_url(self.order)
        self.assertTrue(url.startswith("https://bramanda.example/payments/invoice/"))
        token = urlsplit(url).path.rstrip("/").rsplit("/", 1)[1]
        self.assertEqual(invoice_identity(token)["order"], self.order.pk)

    @override_settings(INVOICE_SIGNING_KEY="")
    def test_missing_signing_key_rejects_invoice(self):
        self.assertEqual(
            self.client.get(
                reverse("payments:signed_invoice", args=["invalid"])
            ).status_code,
            404,
        )

    def test_mutating_method_rejected(self):
        self.assertEqual(self.client.post(self.path()).status_code, 405)
