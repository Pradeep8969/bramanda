from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase, override_settings

from payments.models import Payment
from payments.services import verify_payment

from .emails import queue_confirmation, send_confirmation, template_params
from .models import Order, OrderConfirmationEmail, OrderItem


@override_settings(
    EMAILJS_SERVICE_ID="test-service",
    EMAILJS_ORDER_TEMPLATE_ID="test-template",
    EMAILJS_PUBLIC_KEY="test-public",
    EMAILJS_PRIVATE_KEY="test-private",
    EMAILJS_ATTACHMENT_PARAM="",
    EMAILJS_TEMPLATE_VARIABLES={},
    INVOICE_SIGNING_KEY="test-invoice-signing-key-with-at-least-32-characters",
    BRAMANDA_PUBLIC_BASE_URL="http://127.0.0.1:8000",
)
class EmailJSTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="email-buyer", email="profile@example.com"
        )
        self.order = Order.objects.create(
            customer=user,
            first_name="Asha",
            last_name="Rai",
            email="checkout@example.com",
            phone_number="9800000000",
            shipping_address="Pokhara",
            subtotal=Decimal("500"),
            shipping_cost=Decimal("100"),
            grand_total=Decimal("600"),
        )
        OrderItem.objects.create(
            order=self.order,
            product_name="Purchased Shirt",
            size_name="M",
            color_name="Black",
            sku="SNAPSHOT",
            quantity=2,
            unit_price=250,
            subtotal=500,
        )

    @patch("orders.emails.requests.post", return_value=Mock(status_code=200))
    def test_cod_after_commit_and_duplicate_claim(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
            queue_confirmation(self.order)
            post.assert_not_called()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            OrderConfirmationEmail.objects.get(order=self.order).status, "SENT"
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["accessToken"], "test-private")
        self.assertEqual(payload["template_params"]["to_email"], "checkout@example.com")
        self.assertEqual(payload["template_params"]["items"][0]["unit_price"], "250.00")
        self.assertEqual(payload["template_params"]["shipping_cost"], "100.00")
        self.assertEqual(payload["template_params"]["delivery_address"], "Pokhara")
        from payments.invoice_links import validate_invoice_url

        validate_invoice_url(payload["template_params"]["invoice_url"], self.order)

    @patch("orders.emails.requests.post")
    def test_rollback_does_not_send(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    queue_confirmation(self.order)
                    raise ValueError("rollback")
            except ValueError:
                pass
        post.assert_not_called()
        self.assertFalse(OrderConfirmationEmail.objects.exists())

    @patch("orders.emails.requests.post", return_value=Mock(status_code=200))
    def test_shipping_and_multiple_order_rows_in_sent_payload(self, post):
        OrderItem.objects.create(
            order=self.order,
            product_name="Purchased Trousers",
            size_name="L",
            color_name="Blue",
            sku="SECOND",
            quantity=3,
            unit_price=Decimal("133.50"),
            subtotal=Decimal("400.50"),
        )
        self.order.subtotal = Decimal("900.50")
        self.order.grand_total = Decimal("1000.50")
        self.order.save()
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        params = post.call_args.kwargs["json"]["template_params"]
        self.assertEqual(params["shipping"], "100.00")
        self.assertEqual(params["shipping_cost"], params["shipping"])
        self.assertEqual(params["subtotal"], "900.50")
        self.assertEqual(params["grand_total"], "1000.50")
        self.assertEqual(
            params["orders"],
            [
                {
                    "name": "Purchased Shirt",
                    "units": 2,
                    "price": "250.00",
                    "total": "500.00",
                },
                {
                    "name": "Purchased Trousers",
                    "units": 3,
                    "price": "133.50",
                    "total": "400.50",
                },
            ],
        )
        self.assertEqual(params["payment_method"], "Cash on Delivery")
        self.assertEqual(params["payment_status"], "Unpaid")

    def test_totals_use_saved_values_with_nonstandard_and_zero_shipping(self):
        for shipping in (Decimal("47.25"), Decimal("0.00")):
            self.order.shipping_cost = shipping
            self.order.grand_total = self.order.subtotal + shipping
            self.order.save()
            saved = Order.objects.get(pk=self.order.pk)
            params = template_params(saved)
            self.assertEqual(params["shipping"], f"{shipping:.2f}")
            self.assertEqual(params["subtotal"], "500.00")
            self.assertEqual(params["grand_total"], f"{saved.grand_total:.2f}")

    @patch(
        "orders.emails.OrderConfirmationEmail.objects.get_or_create",
        side_effect=RuntimeError("private"),
    )
    def test_queue_failure_does_not_abort_order(self, create):
        queue_confirmation(self.order)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    @patch(
        "orders.emails.requests.post",
        side_effect=requests.Timeout("secret provider detail"),
    )
    def test_timeout_preserves_order_and_never_auto_resends(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        delivery = OrderConfirmationEmail.objects.get(order=self.order)
        self.assertEqual(delivery.status, "UNKNOWN")
        send_confirmation(delivery.pk)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(Order.objects.get(pk=self.order.pk).order_status, "CONFIRMED")

    @patch("orders.emails.requests.post", return_value=Mock(status_code=429))
    def test_provider_failure_is_recorded(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        self.assertEqual(
            OrderConfirmationEmail.objects.get(order=self.order).error_code, "HTTP_429"
        )

    @patch(
        "orders.emails.requests.post",
        return_value=Mock(
            status_code=403,
            text="API calls are disabled for non-browser applications. private detail",
        ),
    )
    def test_disabled_server_api_records_safe_reason(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        self.assertEqual(
            OrderConfirmationEmail.objects.get(order=self.order).error_code,
            "SERVER_API_DISABLED",
        )

    @patch("orders.emails.requests.post", return_value=Mock(status_code=200))
    def test_explicit_rejected_retry_and_duplicate_protection(self, post):
        delivery = OrderConfirmationEmail.objects.create(
            order=self.order, status="FAILED", error_code="HTTP_403"
        )
        with self.assertRaises(CommandError):
            call_command("retry_order_confirmation", order_id=self.order.pk)
        post.assert_not_called()
        call_command(
            "retry_order_confirmation",
            order_id=self.order.pk,
            confirmed_not_accepted=True,
            stdout=StringIO(),
        )
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "SENT")
        with self.assertRaises(CommandError):
            call_command(
                "retry_order_confirmation",
                order_id=self.order.pk,
                confirmed_not_accepted=True,
            )
        self.assertEqual(post.call_count, 1)

    @patch("orders.emails.requests.post")
    def test_explicit_retry_refuses_uncertain_or_other_failures(self, post):
        delivery = OrderConfirmationEmail.objects.create(order=self.order)
        for status, code in [
            ("UNKNOWN", "DELIVERY_UNCERTAIN"),
            ("SENDING", ""),
            ("FAILED", "HTTP_500"),
            ("SENT", ""),
        ]:
            delivery.status, delivery.error_code = status, code
            delivery.save()
            with self.assertRaises(CommandError):
                call_command(
                    "retry_order_confirmation",
                    order_id=self.order.pk,
                    confirmed_not_accepted=True,
                )
        post.assert_not_called()

    @override_settings(EMAILJS_PRIVATE_KEY="")
    @patch("orders.emails.requests.post")
    def test_missing_configuration_does_not_send(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        post.assert_not_called()
        self.assertEqual(self.order.confirmation_email.status, "PENDING")

    @patch("orders.emails.requests.post", return_value=Mock(status_code=200))
    def test_esewa_only_after_verified_success_and_duplicate_recheck(self, post):
        self.order.payment_method = "ESEWA"
        self.order.payment_status = "PENDING"
        self.order.order_status = "PENDING"
        self.order.save()
        payment = Payment.objects.create(
            order=self.order, payment_method="ESEWA", status="PENDING", amount=600
        )
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        post.assert_not_called()
        data = dict(
            status="COMPLETE",
            pid=str(payment.transaction_uuid),
            scd="EPAYTEST",
            totalAmount="600.00",
            refId="TEST-REFERENCE",
        )
        with patch("payments.esewa.status_response", return_value=data):
            with self.captureOnCommitCallbacks(execute=True):
                verify_payment(payment.pk)
                verify_payment(payment.pk)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            post.call_args.kwargs["json"]["template_params"]["payment_reference"],
            "TEST-REFERENCE",
        )
        params = post.call_args.kwargs["json"]["template_params"]
        self.assertEqual(params["payment_method"], "eSewa")
        self.assertEqual(params["payment_status"], "Paid")
        self.assertEqual(params["shipping"], "100.00")
        self.assertEqual(params["orders"][0]["units"], 2)

    @override_settings(
        EMAILJS_TEMPLATE_VARIABLES={
            "recipient": "to_email",
            "delivery": "shipping_address",
        }
    )
    def test_template_mapping(self):
        params = template_params(self.order)
        self.assertEqual(params["recipient"], "checkout@example.com")
        self.assertEqual(params["delivery"], "Pokhara")

    @override_settings(EMAILJS_ATTACHMENT_PARAM="invoice_pdf")
    def test_no_attachment_even_with_old_attachment_configuration(self):
        params = template_params(self.order)
        self.assertNotIn("invoice_pdf", params)
        self.assertIn("/payments/invoice/", params["invoice_url"])

    @patch("orders.emails.requests.post")
    def test_missing_or_invalid_invoice_url_blocks_send(self, post):
        for url in (
            "",
            None,
            "http://127.0.0.1:8000/payments/invoice/tampered/",
            "https://untrusted.example/invoice/",
        ):
            with self.subTest(url=url), patch(
                "orders.emails.template_params", return_value={"invoice_url": url}
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    queue_confirmation(self.order)
            delivery = OrderConfirmationEmail.objects.get(order=self.order)
            self.assertEqual(delivery.status, "PENDING")
            self.assertEqual(delivery.error_code, "PREPARATION_FAILED")
            self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())
        post.assert_not_called()

    @override_settings(BRAMANDA_PUBLIC_BASE_URL="https://example.com/injected-path")
    @patch("orders.emails.requests.post")
    def test_invalid_origin_blocks_send(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        post.assert_not_called()

    @override_settings(EMAILJS_TEMPLATE_VARIABLES={"invoice_url": "email"})
    @patch("orders.emails.requests.post")
    def test_variable_mapping_cannot_replace_invoice_with_invalid_link(self, post):
        with self.captureOnCommitCallbacks(execute=True):
            queue_confirmation(self.order)
        post.assert_not_called()

    @patch("orders.emails.requests.post")
    def test_expired_and_wrong_order_invoice_urls_block_send(self, post):
        from django.conf import settings
        from django.urls import reverse

        from payments.invoice_links import invoice_url, signer

        with patch("django.core.signing.time.time", return_value=1000000000):
            expired = invoice_url(self.order)
        token = signer().sign_object(
            {
                "order": self.order.pk + 1,
                "customer": self.order.customer_id,
                "number": self.order.order_number,
            }
        )
        wrong_order = settings.BRAMANDA_PUBLIC_BASE_URL + reverse(
            "payments:signed_invoice", args=[token]
        )
        for url in (expired, wrong_order):
            with patch(
                "orders.emails.template_params", return_value={"invoice_url": url}
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    queue_confirmation(self.order)
        post.assert_not_called()
