from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Cart(models.Model):
    # One reusable cart per user; checkout will be a separate later workflow.
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def subtotal(self):
        return sum((item.subtotal for item in self.items.all()), Decimal('0.00'))

    def __str__(self):
        return f'Cart for {self.user}'


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey('products.ProductVariant', on_delete=models.PROTECT, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['cart', 'variant'], name='unique_cart_variant'),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='cart_quantity_positive'),
        ]

    @property
    def unit_price(self):
        return self.variant.product.price

    @property
    def subtotal(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f'{self.variant} × {self.quantity}'

