from django.conf import settings
from django.db import models


class StaffActivity(models.Model):
    class Action(models.TextChoices):
        ORDER_STATUS = 'ORDER_STATUS', 'Order status'
        DELIVERY_STATUS = 'DELIVERY_STATUS', 'Delivery status'
        PAYMENT_STATUS = 'PAYMENT_STATUS', 'Payment status'
        INVENTORY_ADJUSTMENT = 'INVENTORY_ADJUSTMENT', 'Inventory adjustment'

    staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                              null=True, related_name='staff_activities')
    action = models.CharField(max_length=30, choices=Action.choices)
    description = models.TextField()
    reference = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.staff}: {self.get_action_display()} ({self.reference})'
