from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from cart.models import Cart, CartItem
from inventory.models import InventoryTransaction
from orders.models import Order, OrderEvent
from orders.services import create_order_from_cart
from payments.models import Payment
from payments.services import set_cod_payment_status, verify_payment
from products.models import Category, Color, Product, ProductVariant, Size

from .models import StaffActivity


class OrderPaymentManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(
            username="payment-buyer", email="buyer@example.com"
        )
        cls.staff = User.objects.create_user(username="payment-staff", role="STAFF")
        cls.owner = User.objects.create_user(username="payment-owner", role="OWNER")
        product = Product.objects.create(
            name="Essential",
            price=500,
            category=Category.objects.create(name="Essentials"),
        )
        cls.variant = ProductVariant.objects.create(
            product=product,
            sku="PAYMENT-M",
            color=Color.objects.create(name="Black"),
            size=Size.objects.create(name="M"),
            stock_quantity=10,
        )

    def setUp(self):
        network = patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No external payment requests"),
        )
        network.start()
        self.addCleanup(network.stop)
        self.cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=1)

    def place(self, method="COD"):
        self.order = create_order_from_cart(
            self.customer,
            self.cart,
            {
                "first_name": "Asha",
                "last_name": "Rai",
                "email": self.customer.email,
                "phone_number": "9800000001",
                "shipping_address": "Kathmandu",
                "payment_method": method,
            },
        )
        self.payment = self.order.latest_payment

    def url(self, namespace, action="order_detail"):
        return reverse(namespace + ":" + action, args=[self.order.order_number])

    def operators(self):
        return [(self.staff, "dashboard"), (self.owner, "owner")]

    def assert_inventory_unchanged(self):
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 9)
        self.assertEqual(InventoryTransaction.objects.count(), 1)

    def provider_check(self, status, **changes):
        data = {
            "status": status,
            "pid": str(self.payment.transaction_uuid),
            "scd": settings.ESEWA_PRODUCT_CODE,
            "totalAmount": str(self.payment.amount),
            "refId": "VERIFIED-REFERENCE" if status == "COMPLETE" else None,
        }
        data.update(changes)
        with patch("payments.esewa.status_response", return_value=data):
            return verify_payment(self.payment.pk)

    def test_cod_checkout_confirmed_and_payment_remaining_in_both_dashboards(self):
        self.place()
        self.assertEqual(
            (self.order.order_status, self.order.payment_status, self.payment.status),
            ("CONFIRMED", "UNPAID", "UNPAID"),
        )
        for user, namespace in self.operators():
            self.client.force_login(user)
            response = self.client.get(self.url(namespace))
            self.assertContains(response, "Payment Remaining")
            self.assertContains(response, "Confirmed")
            self.assertEqual(
                response.context["payment_form"].initial["payment_status"], "UNPAID"
            )
            self.assertEqual(
                list(response.context["payment_form"].fields["payment_status"].choices),
                [("PAID", "Paid"), ("UNPAID", "Payment Remaining")],
            )
        self.assert_inventory_unchanged()

    def test_both_roles_collect_correct_and_recollect_without_note_or_duplicate(self):
        self.place()
        for user, namespace in self.operators():
            self.client.force_login(user)
            for state in ("PAID", "UNPAID", "PAID", "PAID", "UNPAID"):
                response = self.client.post(
                    self.url(namespace, "payment_status"), {"payment_status": state}
                )
                self.assertEqual(response.status_code, 302)
                self.order.refresh_from_db()
                self.payment.refresh_from_db()
                self.assertEqual(
                    (self.order.payment_status, self.payment.status), (state, state)
                )
                self.assertEqual(self.order.order_status, "CONFIRMED")
                self.assertEqual(self.payment.paid_at is not None, state == "PAID")
                self.assertEqual(self.payment.provider_reference, "")
                self.assertEqual(Payment.objects.count(), 1)
                page = self.client.get(self.url(namespace))
                self.assertEqual(
                    page.context["payment_form"].initial["payment_status"], state
                )
        self.assertEqual(
            StaffActivity.objects.filter(action="PAYMENT_STATUS").count(), 8
        )
        self.assert_inventory_unchanged()
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(
                reverse("payments:receipt", args=[self.order.order_number])
            ).status_code,
            404,
        )

    def test_history_and_order_controls_removed_but_internal_audit_preserved(self):
        self.place()
        event = OrderEvent.objects.create(
            order=self.order,
            actor=self.owner,
            action="INTERNAL_TEST",
            note="Private audit",
        )
        for user, namespace in self.operators():
            self.client.force_login(user)
            response = self.client.get(self.url(namespace))
            for removed in (
                "Order history",
                "Order audit history",
                "No order audit events.",
                "Update order",
                'name="order_status"',
                "Mark payment received",
                "Private audit",
            ):
                self.assertNotContains(response, removed)
            self.assertContains(response, "Update payment", count=1)
            self.assertContains(response, 'name="payment_status"', count=1)
            self.assertContains(response, 'name="delivery_status"', count=1)
            self.assertContains(response, "Update delivery", count=1)
            self.assertNotContains(response, "Payment attempt history")
        self.assertTrue(OrderEvent.objects.filter(pk=event.pk).exists())

    def test_pending_esewa_not_confirmed_or_manually_paid_in_either_dashboard(self):
        self.place("ESEWA")
        for user, namespace in self.operators():
            self.client.force_login(user)
            response = self.client.get(self.url(namespace))
            self.assertContains(response, "Payment Remaining")
            self.assertNotContains(response, 'name="payment_status"')
            self.assertNotContains(response, "Update payment")
            for status in ("PAID", "UNPAID"):
                self.assertEqual(
                    self.client.post(
                        self.url(namespace, "payment_status"),
                        {"payment_status": status},
                    ).status_code,
                    400,
                )
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "delivery_status"),
                    {"delivery_status": "SHIPPED"},
                ).status_code,
                400,
            )
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "order_status"), {"order_status": "CONFIRMED"}
                ).status_code,
                400,
            )
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(
            (self.order.order_status, self.order.payment_status, self.payment.status),
            ("PENDING", "PENDING", "PENDING"),
        )
        self.assertFalse(StaffActivity.objects.exists())
        self.assert_inventory_unchanged()

    def test_verified_esewa_confirms_preserving_reference_and_delivery(self):
        self.place("ESEWA")
        self.provider_check("PENDING")
        self.order.refresh_from_db()
        self.assertEqual(
            (self.order.order_status, self.order.payment_status), ("PENDING", "PENDING")
        )
        self.provider_check("COMPLETE")
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(
            (self.order.order_status, self.order.payment_status), ("CONFIRMED", "PAID")
        )
        self.assertEqual(self.payment.provider_reference, "VERIFIED-REFERENCE")
        self.assertIsNotNone(self.payment.last_verified_at)
        self.assert_inventory_unchanged()
        for user, namespace in self.operators():
            self.client.force_login(user)
            response = self.client.get(self.url(namespace))
            self.assertEqual(response.context["payment_status_label"], "Paid")
            self.assertContains(response, "VERIFIED-REFERENCE")
            self.assertNotContains(response, 'name="payment_status"')
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "payment_status"), {"payment_status": "UNPAID"}
                ).status_code,
                400,
            )
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "delivery_status"),
                    {"delivery_status": "SHIPPED"},
                ).status_code,
                302,
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(self.payment.provider_reference, "VERIFIED-REFERENCE")

    def test_invalid_esewa_verification_never_confirms(self):
        self.place("ESEWA")
        with self.assertRaises(ValidationError):
            self.provider_check("COMPLETE", totalAmount="1")
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(
            (self.order.order_status, self.payment.status), ("PENDING", "PENDING")
        )
        self.assert_inventory_unchanged()

    def test_cod_delivery_progression_and_backwards_rejection_unchanged(self):
        self.place()
        for user, namespace in self.operators():
            self.client.force_login(user)
            for state in (
                "PROCESSING",
                "PACKED",
                "SHIPPED",
                "OUT_FOR_DELIVERY",
                "DELIVERED",
            ):
                Order.objects.filter(pk=self.order.pk).update(delivery_status="PENDING")
                self.assertEqual(
                    self.client.post(
                        self.url(namespace, "delivery_status"),
                        {"delivery_status": state},
                    ).status_code,
                    302,
                )
                self.order.refresh_from_db()
                self.assertEqual(self.order.delivery_status, state)
                self.assertEqual(self.order.payment_status, "UNPAID")
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "delivery_status"),
                    {"delivery_status": "PENDING"},
                ).status_code,
                400,
            )
        self.assert_inventory_unchanged()

    def test_payment_update_requires_role_post_and_csrf(self):
        self.place()
        for user, namespace in self.operators():
            url = self.url(namespace, "payment_status")
            self.client.logout()
            self.assertEqual(
                self.client.post(url, {"payment_status": "PAID"}).status_code, 302
            )
            self.client.force_login(self.customer)
            self.assertEqual(
                self.client.post(url, {"payment_status": "PAID"}).status_code, 403
            )
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 405)
            csrf_client = Client(enforce_csrf_checks=True)
            csrf_client.force_login(user)
            self.assertEqual(
                csrf_client.post(url, {"payment_status": "PAID"}).status_code, 403
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "UNPAID")

    def test_invalid_payment_states_rejected(self):
        self.place()
        for user, namespace in self.operators():
            self.client.force_login(user)
            for state in (
                "PENDING",
                "REFUNDED",
                "FAILED",
                "DELIVERED",
                "CANCELLED",
                "",
            ):
                self.assertEqual(
                    self.client.post(
                        self.url(namespace, "payment_status"), {"payment_status": state}
                    ).status_code,
                    400,
                )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "UNPAID")

    def test_cancelled_cod_does_not_offer_or_accept_payment_changes(self):
        self.place()
        Order.objects.filter(pk=self.order.pk).update(order_status="CANCELLED")
        for user, namespace in self.operators():
            self.client.force_login(user)
            self.assertNotContains(
                self.client.get(self.url(namespace)), "Update payment"
            )
            self.assertEqual(
                self.client.post(
                    self.url(namespace, "payment_status"), {"payment_status": "PAID"}
                ).status_code,
                400,
            )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "UNPAID")

    def test_payment_correction_and_audit_roll_back_together(self):
        self.place()
        set_cod_payment_status(self.order.pk, "PAID")
        self.client.force_login(self.owner)
        with patch(
            "dashboard.views.StaffActivity.objects.create",
            side_effect=RuntimeError("audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    self.url("owner", "payment_status"), {"payment_status": "UNPAID"}
                )
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(
            (self.order.payment_status, self.payment.status), ("PAID", "PAID")
        )
        self.assertIsNotNone(self.payment.paid_at)
        self.assert_inventory_unchanged()

    def test_ambiguous_cod_records_and_gateway_reference_block_correction(self):
        self.place()
        set_cod_payment_status(self.order.pk, "PAID")
        self.client.force_login(self.staff)
        Payment.objects.create(
            order=self.order,
            payment_method="COD",
            status="UNPAID",
            amount=self.order.grand_total,
        )
        self.assertEqual(
            self.client.post(
                self.url("dashboard", "payment_status"), {"payment_status": "UNPAID"}
            ).status_code,
            400,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "PAID")
        self.assertEqual(Payment.objects.count(), 2)
        Payment.objects.exclude(pk=self.payment.pk).delete()
        Payment.objects.filter(pk=self.payment.pk).update(
            provider_reference="UNEXPECTED-GATEWAY-REFERENCE"
        )
        self.assertEqual(
            self.client.post(
                self.url("dashboard", "payment_status"), {"payment_status": "UNPAID"}
            ).status_code,
            400,
        )
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(
            self.payment.provider_reference, "UNEXPECTED-GATEWAY-REFERENCE"
        )

    def test_legacy_cod_without_payment_creates_only_one_record(self):
        self.place()
        self.payment.delete()
        self.client.force_login(self.owner)
        for state in ("PAID", "UNPAID", "PAID"):
            self.assertEqual(
                self.client.post(
                    self.url("owner", "payment_status"), {"payment_status": state}
                ).status_code,
                302,
            )
            self.assertEqual(Payment.objects.count(), 1)
        self.assert_inventory_unchanged()

    def test_clean_payment_summary_for_cod_and_esewa_preserves_records_and_invoices(
        self,
    ):
        for method in ("COD", "ESEWA"):
            with self.subTest(method=method):
                if not self.cart.items.exists():
                    CartItem.objects.create(
                        cart=self.cart, variant=self.variant, quantity=1
                    )
                self.place(method)
                for paid in (False, True):
                    if paid:
                        if method == "COD":
                            set_cod_payment_status(self.order.pk, "PAID")
                        else:
                            self.provider_check("COMPLETE")
                    self.order.refresh_from_db()
                    records = list(Payment.objects.filter(order=self.order).values())
                    inventory = list(InventoryTransaction.objects.values())
                    order_state = (
                        self.order.order_status,
                        self.order.payment_status,
                        self.order.delivery_status,
                    )
                    for user, namespace in self.operators():
                        with self.subTest(paid=paid, role=user.role):
                            self.client.force_login(user)
                            response = self.client.get(self.url(namespace))
                            self.assertEqual(response.status_code, 200)
                            for removed in (
                                "Payment amount:",
                                "View Invoice",
                                "Payment attempt history",
                                "No recorded attempts.",
                                f"#{self.payment.pk} /",
                            ):
                                self.assertNotContains(response, removed)
                            summary = (
                                response.content.decode()
                                .split("<h2>Payment &amp; totals</h2>", 1)[1]
                                .split("</article>", 1)[0]
                            )
                            for retained in (
                                self.order.get_payment_method_display(),
                                "Paid" if paid else "Payment Remaining",
                                "Subtotal",
                                "Shipping",
                                "Grand total",
                                "500.00",
                                "100.00",
                                "600.00",
                            ):
                                self.assertIn(retained, summary)
                            self.assertNotIn("<p></p>", summary)
                            self.assertNotIn("View Payment Receipt", summary)
                            invoice = self.client.get(
                                reverse(
                                    "payments:invoice", args=[self.order.order_number]
                                )
                            )
                            self.assertContains(invoice, "Order Confirmation / Invoice")
                            self.assertContains(invoice, "600.00")
                    self.assertEqual(
                        list(Payment.objects.filter(order=self.order).values()), records
                    )
                    self.assertEqual(
                        list(InventoryTransaction.objects.values()), inventory
                    )
                    self.order.refresh_from_db()
                    self.assertEqual(
                        (
                            self.order.order_status,
                            self.order.payment_status,
                            self.order.delivery_status,
                        ),
                        order_state,
                    )
