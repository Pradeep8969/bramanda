from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase

from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from products.models import Category, Color, Product, ProductVariant, Size

from .models import StaffActivity


class InventoryEditingTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="stock-owner", role="OWNER")
        self.staff = users.create_user(username="stock-staff", role="STAFF")
        self.customer = users.create_user(username="stock-customer", role="CUSTOMER")
        product = Product.objects.create(
            name="apile", price=100, category=Category.objects.create(name="Clothes")
        )
        self.variant = ProductVariant.objects.create(
            product=product,
            color=Color.objects.create(name="Black"),
            size=Size.objects.create(name="M"),
            sku="AP-M",
            stock_quantity=12,
        )
        self.client.force_login(self.owner)

    def payload(self, quantity=20):
        self.variant.refresh_from_db()
        return {
            "variant": self.variant.pk,
            "quantity": quantity,
            "expected_stock": self.variant.stock_quantity,
            "expected_updated_at": self.variant.updated_at.isoformat(),
        }

    def test_owner_and_staff_set_absolute_total_with_history(self):
        for user, prefix in ((self.owner, "/owner"), (self.staff, "/staff")):
            self.client.force_login(user)
            before = self.variant.stock_quantity
            response = self.client.post(
                prefix + "/inventory/update/", self.payload(before + 8)
            )
            self.assertEqual(response.status_code, 200)
            self.variant.refresh_from_db()
            self.assertEqual(self.variant.stock_quantity, before + 8)
            record = InventoryTransaction.objects.latest("pk")
            self.assertEqual(
                (record.previous_stock, record.quantity, record.new_stock),
                (before, 8, before + 8),
            )
            self.assertEqual(record.created_by, user)
            self.assertEqual(record.note, "Stock updated from inventory dashboard")
        self.assertEqual(StaffActivity.objects.count(), 2)

    def test_zero_and_unchanged_quantity(self):
        self.assertEqual(
            self.client.post("/owner/inventory/update/", self.payload(12)).status_code,
            200,
        )
        self.assertFalse(InventoryTransaction.objects.exists())
        response = self.client.post("/owner/inventory/update/", self.payload(0))
        self.assertEqual(response.json()["stock_level"], "Out of Stock")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 0)
        self.assertEqual(InventoryTransaction.objects.get().quantity, -12)

    def test_invalid_and_missing_values(self):
        for quantity in (-1, "1.5", "12.0", "abc", "", "1e2", 2147483648):
            with self.subTest(quantity=quantity):
                self.assertEqual(
                    self.client.post(
                        "/owner/inventory/update/", self.payload(quantity)
                    ).status_code,
                    400,
                )
        for field in ("variant", "expected_stock", "expected_updated_at"):
            data = self.payload()
            del data[field]
            self.assertEqual(
                self.client.post("/owner/inventory/update/", data).status_code, 400
            )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 12)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_permissions_and_methods(self):
        for user, expected in ((self.customer, 403), (self.staff, 403)):
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(
                    "/owner/inventory/update/", self.payload()
                ).status_code,
                expected,
            )
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.post("/staff/inventory/update/", self.payload()).status_code,
            403,
        )
        self.client.logout()
        self.assertEqual(
            self.client.post("/staff/inventory/update/", self.payload()).status_code,
            302,
        )
        self.staff.is_active = False
        self.staff.save()
        self.client.force_login(self.staff)
        self.assertNotEqual(
            self.client.post("/staff/inventory/update/", self.payload()).status_code,
            200,
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/owner/inventory/update/").status_code, 405)
        self.assertFalse(InventoryTransaction.objects.exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(
            client.post("/owner/inventory/update/", self.payload()).status_code, 403
        )

    def test_stale_edits_and_checkout_changes_are_rejected(self):
        stale = self.payload()
        self.assertEqual(
            self.client.post("/owner/inventory/update/", stale).status_code, 200
        )
        self.assertEqual(
            self.client.post("/owner/inventory/update/", stale).status_code, 409
        )
        stale = self.payload(30)
        adjust_stock(self.variant, -2, "ORDER")
        self.assertEqual(
            self.client.post("/owner/inventory/update/", stale).status_code, 409
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 18)
        self.assertEqual(InventoryTransaction.objects.count(), 2)

    def test_stock_returning_to_same_total_still_conflicts(self):
        stale = self.payload()
        adjust_stock(self.variant, -1, "ORDER")
        adjust_stock(self.variant, 1, "RETURN")
        self.assertEqual(
            self.client.post("/owner/inventory/update/", stale).status_code, 409
        )
        self.assertEqual(InventoryTransaction.objects.count(), 2)

    def test_audit_and_database_failure_roll_back(self):
        for target in (
            "dashboard.views.StaffActivity.objects.create",
            "inventory.services.InventoryTransaction.save",
        ):
            with patch(target, side_effect=DatabaseError("failed")):
                self.assertEqual(
                    self.client.post(
                        "/owner/inventory/update/", self.payload()
                    ).status_code,
                    409,
                )
            self.variant.refresh_from_db()
            self.assertEqual(self.variant.stock_quantity, 12)
            self.assertFalse(InventoryTransaction.objects.exists())
            self.assertFalse(StaffActivity.objects.exists())

    def test_table_and_inactive_variant_permissions(self):
        for user, prefix in ((self.owner, "/owner"), (self.staff, "/staff")):
            self.client.force_login(user)
            response = self.client.get(prefix + "/inventory/")
            self.assertContains(response, 'name="quantity"')
            self.assertContains(response, "disabled>Save")
            self.assertNotContains(response, "Submit Adjustment")
            self.assertNotContains(response, "Note / reason")
        self.variant.is_active = False
        self.variant.save()
        self.assertEqual(
            self.client.post("/staff/inventory/update/", self.payload()).status_code,
            400,
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post("/owner/inventory/update/", self.payload()).status_code,
            200,
        )
