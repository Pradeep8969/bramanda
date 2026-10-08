from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import DatabaseError

from payments.models import Payment
from payments.services import verify_payment


class Command(BaseCommand):
    help = 'Re-check pending eSewa UAT attempts; verified terminal failures release stock exactly once.'

    def handle(self, *args, **options):
        for payment in Payment.objects.filter(payment_method='ESEWA', status='PENDING').iterator():
            try:
                verified = verify_payment(payment.pk)
                self.stdout.write(f'{payment.transaction_uuid}: {verified.status}')
            except (ValidationError, DatabaseError):
                self.stderr.write(f'{payment.transaction_uuid}: reconciliation deferred; staff review required.')
