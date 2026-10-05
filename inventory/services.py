from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from products.models import ProductVariant
from .models import InventoryTransaction


@transaction.atomic
def adjust_stock(variant, quantity_change, transaction_type, user=None, reference='', note=''):
    """Change stock and record its history together, or roll back both."""
    types = InventoryTransaction.TransactionType
    if transaction_type not in types.values:
        raise ValidationError('Invalid inventory transaction type.')
    if isinstance(quantity_change, bool) or not isinstance(quantity_change, int) or quantity_change == 0:
        raise ValidationError('Quantity change must be a nonzero integer.')
    if transaction_type in (types.STOCK_IN, types.RETURN) and quantity_change < 0:
        raise ValidationError('Stock in and returns must increase stock.')
    if transaction_type in (types.STOCK_OUT, types.ORDER) and quantity_change > 0:
        raise ValidationError('Stock out and orders must decrease stock.')

    locked_variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
    previous_stock = locked_variant.stock_quantity
    new_stock = previous_stock + quantity_change
    if new_stock < 0:
        raise ValidationError('Insufficient stock: stock cannot become negative.')

    record = InventoryTransaction(
        variant=locked_variant, transaction_type=transaction_type,
        quantity=quantity_change, previous_stock=previous_stock, new_stock=new_stock,
        created_by=user, reference=reference, note=note,
    )
    record.full_clean()
    # SQLite has no row locks. This comparison also prevents a stale overwrite.
    updated = ProductVariant.objects.filter(pk=locked_variant.pk, stock_quantity=previous_stock).update(
        stock_quantity=new_stock, updated_at=timezone.now(),
    )
    if updated != 1:
        raise ValidationError('Stock changed concurrently. Please retry.')
    record.save()
    return record
