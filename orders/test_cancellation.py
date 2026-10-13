"""Cancellation is retired; historical data and payment reconciliation remain safe."""

import base64
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from inventory.models import InventoryTransaction
from payments import tests as payment_fixtures
from payments.services import collect_cod, retry_esewa

from .models import CancellationRequest, Order, OrderEvent


class CancellationRemovalTests(TestCase):
    setUp = payment_fixtures.PaymentTests.setUp
    checkout_data = payment_fixtures.PaymentTests.checkout_data
    place = payment_fixtures.PaymentTests.place
    provider_status = payment_fixtures.PaymentTests.provider_status
    callback = payment_fixtures.PaymentTests.callback
    verify = payment_fixtures.PaymentTests.verify
    url = payment_fixtures.PaymentTests.url

    def historical_order(self, method="ESEWA", paid=False, released=True):
        # Build a historical snapshot directly, without a retired service.
        self.place(method)
        if paid:
            self.verify()
        if released:
            InventoryTransaction.objects.create(
                variant=self.variant,
                transaction_type="RETURN",
                quantity=2,
                previous_stock=8,
                new_stock=10,
                reference=self.order.order_number,
            )
            type(self.variant).objects.filter(pk=self.variant.pk).update(
                stock_quantity=10
            )
        Order.objects.filter(pk=self.order.pk).update(
            order_status="CANCELLED",
            cancelled_at=timezone.now(),
            payment_stock_released=released,
        )
        self.order.refresh_from_db()
        self.history = CancellationRequest.objects.create(
            order=self.order,
            requested_by=self.user,
            reason="Historical record",
            status="APPROVED",
        )
        OrderEvent.objects.create(
            order=self.order, action="CANCELLED", note="Historical record"
        )

    def stock(self):
        self.variant.refresh_from_db()
        return self.variant.stock_quantity

    def test_old_routes_are_404_for_every_role_and_method_without_mutation(self):
        self.place("COD")
        pending = CancellationRequest.objects.create(
            order=self.order, requested_by=self.user
        )
        paths = [
            f"/orders/{self.order.order_number}/cancel/",
            "/owner/cancellations/",
            "/staff/cancellations/",
            f"/owner/cancellations/{pending.pk}/review/",
            f"/staff/cancellations/{pending.pk}/review/",
        ]
        for user in (None, self.user, self.other, self.owner, self.staff):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for path in paths:
                for method in ("get", "post"):
                    for decision in ("APPROVED", "REJECTED"):
                        with self.subTest(
                            user=user, path=path, method=method, decision=decision
                        ):
                            self.assertEqual(
                                getattr(self.client, method)(
                                    path, {"decision": decision, "reason": "Cancel"}
                                ).status_code,
                                404,
                            )
        self.order.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.order.order_status, "CONFIRMED")
        self.assertEqual(pending.status, "PENDING")
        self.assertEqual(self.stock(), 8)
        self.assertFalse(OrderEvent.objects.exists())
        self.assertEqual(
            InventoryTransaction.objects.filter(transaction_type="RETURN").count(), 0
        )
        for name, args in [
            ("orders:cancel", [self.order.order_number]),
            ("owner:cancellations", []),
            ("dashboard:cancellations", []),
            ("owner:cancellation_review", [pending.pk]),
            ("dashboard:cancellation_review", [pending.pk]),
        ]:
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=args)

    def test_customer_pages_and_dashboard_tabs_have_no_cancellation_controls(self):
        self.place("COD")
        paths = [
            reverse("orders:list"),
            reverse("orders:detail", args=[self.order.order_number]),
            reverse("orders:success", args=[self.order.order_number]),
        ]
        for path in paths:
            response = self.client.get(path)
            self.assertContains(response, self.order.order_number)
            for text in (
                "Cancel Order",
                "Request Cancellation",
                "/cancel/",
                "Cancellation Requested",
            ):
                self.assertNotContains(response, text)
        for user, namespace in [(self.owner, "owner"), (self.staff, "dashboard")]:
            self.client.force_login(user)
            for route in ("home", "orders", "order_detail"):
                args = [self.order.order_number] if route == "order_detail" else []
                response = self.client.get(reverse(namespace + ":" + route, args=args))
                self.assertEqual(response.status_code, 200)
                for text in (
                    "Cancellations",
                    "/cancellations/",
                    "Approve cancellation",
                    "Reject request",
                    "Manage cancellation requests",
                    'value="CANCELLED"',
                ):
                    if route != "orders":  # Historical status filters remain valid.
                        self.assertNotContains(response, text)
                    else:
                        self.assertNotContains(response, "/cancellations/")

    def test_manual_cancellation_rejected_and_delivery_updates_work(self):
        self.place("COD")
        for user, namespace in [(self.owner, "owner"), (self.staff, "dashboard")]:
            self.client.force_login(user)
            response = self.client.post(
                reverse(namespace + ":order_status", args=[self.order.order_number]),
                {"order_status": "CANCELLED"},
            )
            self.assertEqual(response.status_code, 400)
            self.order.refresh_from_db()
            self.assertEqual(self.order.order_status, "CONFIRMED")
            response = self.client.post(
                reverse(namespace + ":delivery_status", args=[self.order.order_number]),
                {"delivery_status": "SHIPPED"},
            )
            self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_status, "SHIPPED")
        self.assertEqual(self.stock(), 8)

    def test_historical_records_visible_preserved_and_fulfillment_blocked(self):
        self.historical_order("COD")
        self.assertContains(
            self.client.get(reverse("orders:detail", args=[self.order.order_number])),
            "This order has been cancelled.",
        )
        for user, namespace in [(self.owner, "owner"), (self.staff, "dashboard")]:
            self.client.force_login(user)
            self.assertContains(
                self.client.get(
                    reverse(namespace + ":order_detail", args=[self.order.order_number])
                ),
                "Cancelled",
            )
            for route, data in [
                ("order_status", {"order_status": "PROCESSING"}),
                ("delivery_status", {"delivery_status": "SHIPPED"}),
                ("payment_status", {"payment_status": "PAID"}),
            ]:
                self.assertEqual(
                    self.client.post(
                        reverse(
                            namespace + ":" + route, args=[self.order.order_number]
                        ),
                        data,
                    ).status_code,
                    400,
                )
        with self.assertRaises(ValidationError):
            collect_cod(self.order.pk)
        self.assertEqual(self.stock(), 10)
        self.history.refresh_from_db()
        self.assertEqual(self.history.reason, "Historical record")
        self.assertEqual(OrderEvent.objects.filter(action="CANCELLED").count(), 1)

    def test_signed_late_callbacks_record_funds_once_without_stock_or_status_changes(
        self,
    ):
        self.historical_order()
        with patch(
            "payments.esewa.status_response", return_value=self.provider_status()
        ):
            for _ in range(2):
                response = self.client.get(
                    self.url("esewa_success"), {"data": self.callback()}
                )
                self.assertEqual(response.url, self.url("result"))
        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.order.order_status, "CANCELLED")
        self.assertEqual(self.order.delivery_status, "PENDING")
        self.assertEqual(self.order.payment_status, "PAID")
        self.assertTrue(self.payment.review_required)
        self.assertEqual(self.stock(), 10)
        self.assertEqual(
            InventoryTransaction.objects.filter(transaction_type="RETURN").count(), 1
        )
        self.assertEqual(
            OrderEvent.objects.filter(action="LATE_PAYMENT_RECONCILIATION").count(), 1
        )
        with self.assertRaises(ValidationError):
            retry_esewa(self.order.pk)

    def test_late_payment_does_not_change_unreleased_historical_stock(self):
        self.historical_order(released=False)
        self.verify()
        self.order.refresh_from_db()
        self.assertEqual(self.order.order_status, "CANCELLED")
        self.assertEqual(self.stock(), 8)
        self.assertFalse(
            InventoryTransaction.objects.filter(transaction_type="RETURN").exists()
        )

    def test_old_provider_responses_preserve_verified_historical_payment(self):
        self.historical_order(paid=True)
        original = (
            self.order.latest_payment.paid_at,
            self.order.latest_payment.transaction_code,
        )
        for status in ("PENDING", "CANCELED", "NOT_FOUND", "COMPLETE"):
            self.verify(status)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(
            (self.payment.paid_at, self.payment.transaction_code), original
        )
        self.assertEqual(self.order.order_status, "CANCELLED")
        self.assertEqual(self.stock(), 10)

    def test_invalid_late_signature_never_records_payment(self):
        self.historical_order()
        data = json.loads(base64.b64decode(self.callback()))
        data["signature"] = "invalid"
        malformed = base64.b64encode(json.dumps(data).encode()).decode()
        with patch("payments.esewa.status_response") as provider:
            self.assertEqual(
                self.client.get(
                    self.url("esewa_success"), {"data": malformed}
                ).status_code,
                400,
            )
            provider.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PENDING")
        self.assertEqual(self.stock(), 10)

    def test_historical_pending_constraint_and_audit_immutability(self):
        self.place("COD")
        CancellationRequest.objects.create(order=self.order, requested_by=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CancellationRequest.objects.create(order=self.order, requested_by=self.user)
        event = OrderEvent.objects.create(
            order=self.order, action="CANCELLATION_REQUESTED"
        )
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()
        with self.assertRaises(ValueError):
            OrderEvent.objects.filter(pk=event.pk).update(note="Changed")
        with self.assertRaises(ValueError):
            OrderEvent.objects.filter(pk=event.pk).delete()
