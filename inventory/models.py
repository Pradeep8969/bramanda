from django.conf import settings
from django.db import models


class InventoryTransaction(models.Model):
    class TransactionType(models.TextChoices):
        STOCK_IN = 'STOCK_IN', 'Stock in'
        STOCK_OUT = 'STOCK_OUT', 'Stock out'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'
        ORDER = 'ORDER', 'Order'
        RETURN = 'RETURN', 'Return'

    variant = models.ForeignKey('products.ProductVariant', on_delete=models.PROTECT, related_name='inventory_transactions')
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    # Signed change: positive adds stock, negative removes stock.
    quantity = models.IntegerField()
    previous_stock = models.PositiveIntegerField()
    new_stock = models.PositiveIntegerField()
    reference = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventory_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(transaction_type__in=['STOCK_IN', 'STOCK_OUT', 'ADJUSTMENT', 'ORDER', 'RETURN']), name='inventory_valid_type'),
            models.CheckConstraint(condition=models.Q(new_stock=models.F('previous_stock') + models.F('quantity')), name='inventory_stock_matches_change'),
        ]

    def __str__(self):
        return f'{self.variant.sku}: {self.quantity:+d} ({self.get_transaction_type_display()})'
