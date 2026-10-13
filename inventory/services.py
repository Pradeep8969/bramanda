from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from products.models import ProductVariant

from .models import InventoryTransaction


@transaction.atomic
def adjust_stock(
    variant,
    quantity_change,
    transaction_type,
    user=None,
    reference="",
    note="",
    adjustment_key=None,
):
    """Change stock and record its history together, or roll back both."""
    types = InventoryTransaction.TransactionType
    if transaction_type not in types.values:
        raise ValidationError("Invalid inventory transaction type.")
    if (
        isinstance(quantity_change, bool)
        or not isinstance(quantity_change, int)
        or quantity_change == 0
    ):
        raise ValidationError("Quantity change must be a nonzero integer.")
    if transaction_type in (types.STOCK_IN, types.RETURN) and quantity_change < 0:
        raise ValidationError("Stock in and returns must increase stock.")
    if transaction_type in (types.STOCK_OUT, types.ORDER) and quantity_change > 0:
        raise ValidationError("Stock out and orders must decrease stock.")

    locked_variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    if (
        adjustment_key is not None
        and InventoryTransaction.objects.filter(adjustment_key=adjustment_key).exists()
    ):
        raise ValidationError(
            "This adjustment has already been saved. Reload inventory to start a new adjustment."
        )
    previous_stock = locked_variant.stock_quantity
    new_stock = previous_stock + quantity_change
    if new_stock < 0:
        raise ValidationError("Insufficient stock: stock cannot become negative.")

    record = InventoryTransaction(
        variant=locked_variant,
        transaction_type=transaction_type,
        quantity=quantity_change,
        previous_stock=previous_stock,
        new_stock=new_stock,
        created_by=user,
        reference=reference,
        note=note,
        adjustment_key=adjustment_key,
    )
    record.full_clean()
    # SQLite has no row locks. This comparison also prevents a stale overwrite.
    updated = ProductVariant.objects.filter(
        pk=locked_variant.pk, stock_quantity=previous_stock
    ).update(
        stock_quantity=new_stock,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise ValidationError("Stock changed concurrently. Please retry.")
    record.save()
    return record


class StockConflict(ValidationError):
    """The inventory row has changed since the dashboard loaded."""


@transaction.atomic
def set_stock(variant, quantity, expected_stock, expected_updated_at, user=None):
    """Set an absolute total through the audited adjustment service."""
    for value in (quantity, expected_stock):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 2147483647
        ):
            raise ValidationError("Stock must be a non-negative whole number.")
    locked = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    if (
        locked.stock_quantity != expected_stock
        or locked.updated_at.isoformat() != expected_updated_at
    ):
        raise StockConflict(
            "Stock changed since this row loaded. Reload inventory before saving again."
        )
    if quantity == locked.stock_quantity:
        return locked, None
    record = adjust_stock(
        locked,
        quantity - locked.stock_quantity,
        InventoryTransaction.TransactionType.ADJUSTMENT,
        user=user,
        reference=f"{user.role}-{user.pk}" if user else "",
        note="Stock updated from inventory dashboard",
    )
    locked.refresh_from_db()
    return locked, record
