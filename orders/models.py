from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def generate_order_number():
    # Random suffix plus a database uniqueness constraint avoids sequence races.
    return f'BRM-{timezone.now():%Y%m%d}-{uuid4().hex[:16].upper()}'


class Order(models.Model):
    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        PROCESSING = 'PROCESSING', 'Processing'
        PACKED = 'PACKED', 'Packed'
        SHIPPED = 'SHIPPED', 'Shipped'
        DELIVERED = 'DELIVERED', 'Delivered'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        REFUNDED = 'REFUNDED', 'Refunded'

    class DeliveryStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        PACKED = 'PACKED', 'Packed'
        SHIPPED = 'SHIPPED', 'Shipped'
        OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY', 'Out for delivery'
        DELIVERED = 'DELIVERED', 'Delivered'

    class PaymentMethod(models.TextChoices):
        COD = 'COD', 'Cash on Delivery'
        ESEWA = 'ESEWA', 'eSewa'

    order_number = models.CharField(max_length=40, unique=True, default=generate_order_number, editable=False)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone_number = models.CharField(max_length=30)
    shipping_address = models.TextField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    shipping_cost = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.COD)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_stock_released = models.BooleanField(default=False)
    order_status = models.CharField(max_length=10, choices=OrderStatus.choices, default=OrderStatus.CONFIRMED)
    delivery_status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, shipping_cost__gte=0, grand_total__gte=0), name='order_money_nonnegative'),
        ]

    @property
    def tracking_steps(self):
        labels = ['Confirmed', 'Processing', 'Packed', 'Shipped', 'Out for delivery', 'Delivered']
        order_stages = {'PENDING': -1, 'CONFIRMED': 0, 'PROCESSING': 1, 'PACKED': 2, 'SHIPPED': 3, 'DELIVERED': 5}
        delivery_stages = {'PENDING': -1, 'PROCESSING': 1, 'PACKED': 2, 'SHIPPED': 3, 'OUT_FOR_DELIVERY': 4, 'DELIVERED': 5}
        if self.order_status == self.OrderStatus.CANCELLED:
            return []
        current = max(order_stages.get(self.order_status, -1), delivery_stages.get(self.delivery_status, -1))
        return [{'label': label, 'state': 'current' if index == current else 'complete' if index < current else 'upcoming'}
                for index, label in enumerate(labels)]

    def __str__(self):
        return self.order_number

    @property
    def latest_payment(self):
        return self.payments.order_by('-created_at', '-pk').first()

    @property
    def can_retry_payment(self):
        return (self.payment_method == self.PaymentMethod.ESEWA
                and self.payment_status in (self.PaymentStatus.FAILED, self.PaymentStatus.CANCELLED)
                and self.payment_stock_released)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    variant = models.ForeignKey('products.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    product_name = models.CharField(max_length=200)
    size_name = models.CharField(max_length=20)
    color_name = models.CharField(max_length=50)
    sku = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        ordering = ['pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1, unit_price__gte=0, subtotal__gte=0), name='order_item_positive_quantity_money'),
        ]

    def __str__(self):
        return f'{self.product_name} / {self.color_name} / {self.size_name}'

