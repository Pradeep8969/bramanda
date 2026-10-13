import json
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from payments import esewa
from payments.models import Payment


class Command(BaseCommand):
    help = "Read-only eSewa UAT status diagnostic. Does not reconcile, charge, or alter payment/order records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--payment-id",
            type=int,
            help="Internal payment ID; defaults to latest pending eSewa attempt.",
        )

    def handle(self, *args, **options):
        payments = Payment.objects.filter(payment_method="ESEWA")
        payment = (
            payments.filter(pk=options["payment_id"]).first()
            if options["payment_id"]
            else payments.filter(status="PENDING").first()
        )
        if payment is None:
            raise CommandError(
                "No matching eSewa attempt. Specify an existing internal --payment-id."
            )
        diagnostics = {
            "endpoint_host": urlsplit(settings.ESEWA_STATUS_URL).hostname,
            "merchant_matches_uat": payment.merchant_code
            == settings.ESEWA_PRODUCT_CODE
            == "EPAYTEST",
            "signing_key_matches_published_uat": settings.ESEWA_SECRET_KEY
            == "8gBm/:&EnhH.1/q",
            "read_only": True,
        }
        try:
            data = esewa.status_response(payment)
            diagnostics.update(getattr(payment, "_verification_diagnostics", {}))
            status, _reference = esewa.validate_status(data, payment)
            diagnostics.update(
                identity_and_amount_match=True,
                provider_status=(
                    status
                    if status
                    in (
                        "COMPLETE",
                        "PENDING",
                        "NOT_FOUND",
                        "CANCELED",
                        "FULL_REFUND",
                        "PARTIAL_REFUND",
                        "AMBIGUOUS",
                        "AMBIGIOUS",
                        "FAILED",
                        "CANCELLED",
                    )
                    else "UNRECOGNIZED"
                ),
            )
        except esewa.VerificationError as error:
            diagnostics.update(
                error.diagnostics,
                error_code=error.error_code,
                message="; ".join(error.messages),
            )
        except ValidationError:
            diagnostics.update(
                error_code="CONFIGURATION_ERROR",
                message="Check the server-side eSewa configuration.",
            )
        self.stdout.write(json.dumps(diagnostics, sort_keys=True))
