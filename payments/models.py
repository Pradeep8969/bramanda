from uuid import uuid4

from django.db import models

from orders.models import Order


class Payment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    payment_method = models.CharField(
        max_length=20, choices=Order.PaymentMethod.choices
    )
    status = models.CharField(max_length=10, choices=Order.PaymentStatus.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    transaction_uuid = models.UUIDField(default=uuid4, unique=True, editable=False)
    transaction_code = models.CharField(max_length=100, blank=True)
    provider_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    review_required = models.BooleanField(default=False)
    merchant_code = models.CharField(max_length=50, default="EPAYTEST", editable=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    provider_status = models.CharField(max_length=30, blank=True)
    verification_error = models.CharField(max_length=250, blank=True)
    verification_started_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="payment_amount_nonnegative"
            ),
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="PENDING"),
                name="one_pending_payment_per_order",
            ),
        ]

    def __str__(self):
        return f"{self.order.order_number}: {self.payment_method} {self.status}"


class PaymentVerification(models.Model):
    payment = models.ForeignKey(
        Payment, on_delete=models.CASCADE, related_name="verifications"
    )
    checked_at = models.DateTimeField(auto_now_add=True)
    provider_status = models.CharField(max_length=30, blank=True)
    error = models.CharField(max_length=250, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    error_code = models.CharField(max_length=40, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_format = models.CharField(max_length=10, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
