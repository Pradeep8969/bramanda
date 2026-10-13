from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def generate_order_number():
    # Random suffix plus a database uniqueness constraint avoids sequence races.
    return f"BRM-{timezone.now():%Y%m%d}-{uuid4().hex[:16].upper()}"


class Order(models.Model):
    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PROCESSING = "PROCESSING", "Processing"
        PACKED = "PACKED", "Packed"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    class DeliveryStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        PACKED = "PACKED", "Packed"
        SHIPPED = "SHIPPED", "Shipped"
        OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY", "Out for delivery"
        DELIVERED = "DELIVERED", "Delivered"

    class PaymentMethod(models.TextChoices):
        COD = "COD", "Cash on Delivery"
        ESEWA = "ESEWA", "eSewa"

    order_number = models.CharField(
        max_length=40, unique=True, default=generate_order_number, editable=False
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField()
    phone_number = models.CharField(max_length=30)
    shipping_address = models.TextField()
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    shipping_cost = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    grand_total = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.COD
    )
    payment_status = models.CharField(
        max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    payment_stock_released = models.BooleanField(default=False)
    order_status = models.CharField(
        max_length=10, choices=OrderStatus.choices, default=OrderStatus.CONFIRMED
    )
    delivery_status = models.CharField(
        max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    workflow_version = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    subtotal__gte=0, shipping_cost__gte=0, grand_total__gte=0
                ),
                name="order_money_nonnegative",
            ),
        ]

    @property
    def tracking_steps(self):
        labels = [
            "Confirmed",
            "Processing",
            "Packed",
            "Shipped",
            "Out for delivery",
            "Delivered",
        ]
        order_stages = {
            "PENDING": -1,
            "CONFIRMED": 0,
            "PROCESSING": 1,
            "PACKED": 2,
            "SHIPPED": 3,
            "DELIVERED": 5,
        }
        delivery_stages = {
            "PENDING": -1,
            "PROCESSING": 1,
            "PACKED": 2,
            "SHIPPED": 3,
            "OUT_FOR_DELIVERY": 4,
            "DELIVERED": 5,
        }
        if self.order_status == self.OrderStatus.CANCELLED:
            return []
        current = max(
            order_stages.get(self.order_status, -1),
            delivery_stages.get(self.delivery_status, -1),
        )
        return [
            {
                "label": label,
                "state": (
                    "current"
                    if index == current
                    else "complete" if index < current else "upcoming"
                ),
            }
            for index, label in enumerate(labels)
        ]

    def __str__(self):
        return self.order_number

    @property
    def latest_payment(self):
        return self.payments.order_by("-created_at", "-pk").first()

    @property
    def can_retry_payment(self):
        return (
            self.cancelled_at is None
            and self.payment_method == self.PaymentMethod.ESEWA
            and self.payment_status
            in (self.PaymentStatus.FAILED, self.PaymentStatus.CANCELLED)
            and self.payment_stock_released
        )


class OrderConfirmationEmail(models.Model):
    """One durable delivery claim per order; ambiguous sends are never auto-retried."""

    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="confirmation_email"
    )
    status = models.CharField(max_length=16, default="PENDING")
    attempted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=40, blank=True)


class CancellationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    order = models.ForeignKey(
        Order, on_delete=models.PROTECT, related_name="cancellation_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cancellation_requests",
    )
    reason = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cancellation_reviews",
    )
    decision_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="PENDING"),
                name="one_active_order_cancellation",
            )
        ]
        indexes = [
            models.Index(
                fields=["status", "requested_at"], name="cancellation_queue_idx"
            )
        ]


class OrderEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("Order events are append-only.")

    def delete(self):
        raise ValueError("Order events are append-only.")


class OrderEvent(models.Model):
    objects = OrderEventQuerySet.as_manager()
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    action = models.CharField(max_length=40)
    note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Order events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Order events are append-only.")


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    variant = models.ForeignKey(
        "products.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=200)
    size_name = models.CharField(max_length=20)
    color_name = models.CharField(max_length=50)
    sku = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1, unit_price__gte=0, subtotal__gte=0),
                name="order_item_positive_quantity_money",
            ),
        ]

    def __str__(self):
        return f"{self.product_name} / {self.color_name} / {self.size_name}"
