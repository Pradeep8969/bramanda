"""Explicit retry of one rejected confirmation after provider history review."""

from django.core.management.base import BaseCommand, CommandError

from orders.emails import eligible, send_confirmation, template_params
from orders.models import OrderConfirmationEmail


class Command(BaseCommand):
    help = "Retry one HTTP 403 rejection after configuration repair and history review."

    def add_arguments(self, parser):
        parser.add_argument("--order-id", type=int, required=True)
        parser.add_argument("--confirmed-not-accepted", action="store_true")

    def handle(self, *args, **options):
        if not options["confirmed_not_accepted"]:
            raise CommandError(
                "Check EmailJS history for this order first; then pass --confirmed-not-accepted."
            )
        delivery = (
            OrderConfirmationEmail.objects.select_related("order")
            .filter(order_id=options["order_id"])
            .first()
        )
        if delivery is None:
            raise CommandError("No delivery record exists. No email was sent.")
        if not eligible(delivery.order):
            raise CommandError("Order is not eligible. No email was sent.")
        try:
            template_params(delivery.order)
        except Exception:
            raise CommandError(
                "Invoice/template preparation failed. No email was sent."
            ) from None
        # Compare-and-set: concurrent retries cannot both reclaim a failed record.
        updated = OrderConfirmationEmail.objects.filter(
            pk=delivery.pk,
            status="FAILED",
            sent_at__isnull=True,
            error_code__in=["HTTP_403", "SERVER_API_DISABLED"],
        ).update(status="PENDING", error_code="")
        if not updated:
            raise CommandError(
                "Only a recorded HTTP 403 rejection can be retried; delivery was unchanged."
            )
        send_confirmation(delivery.pk)
        delivery.refresh_from_db()
        self.stdout.write(
            f"Order {delivery.order_id}: {delivery.status} {delivery.error_code}".rstrip()
        )
