"""Deliver pending confirmations, including those interrupted before HTTP."""

import time

from django.core.management.base import BaseCommand

from orders.emails import send_confirmation
from orders.models import OrderConfirmationEmail


class Command(BaseCommand):
    help = (
        "Send pending order confirmations; never resend sent or uncertain deliveries."
    )

    def handle(self, *args, **options):
        ids = list(
            OrderConfirmationEmail.objects.filter(status="PENDING").values_list(
                "pk", flat=True
            )
        )
        for index, delivery_id in enumerate(ids):
            if index:
                time.sleep(1.05)  # EmailJS permits one request per second.
            send_confirmation(delivery_id)
        self.stdout.write(f"Processed {len(ids)} pending confirmations.")
