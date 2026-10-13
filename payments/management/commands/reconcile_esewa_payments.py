from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import DatabaseError

from payments.models import Payment
from payments.services import verify_payment


class Command(BaseCommand):
    help = "Re-check pending eSewa UAT attempts; verified terminal failures release stock exactly once."

    def handle(self, *args, **options):
        for payment in Payment.objects.filter(
            payment_method="ESEWA", status="PENDING"
        ).iterator():
            try:
                verified = verify_payment(payment.pk)
                verified.refresh_from_db()
                if verified.verification_error:
                    self.stderr.write(
                        f"Payment {payment.pk}: verification error; {verified.verification_error}"
                    )
                else:
                    self.stdout.write(
                        f"Payment {payment.pk}: {verified.status} (provider: {verified.provider_status})"
                    )
            except (ValidationError, DatabaseError):
                self.stderr.write(
                    f"Payment {payment.pk}: reconciliation deferred; check verification history for the safe error code."
                )
