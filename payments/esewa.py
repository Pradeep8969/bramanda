import base64
import binascii
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse

REQUEST_FIELDS = 'total_amount,transaction_uuid,product_code'
RESPONSE_FIELDS = 'transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names'


def signature(message):
    if not settings.ESEWA_SECRET_KEY:
        raise ValidationError('Configure the eSewa UAT signing key before paying.')
    return base64.b64encode(hmac.new(settings.ESEWA_SECRET_KEY.encode(), message.encode(),
                                    hashlib.sha256).digest()).decode()


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Invalid payment amount.')


def form_fields(payment):
    order = payment.order
    if payment.amount != order.grand_total or order.subtotal + order.shipping_cost != order.grand_total:
        raise ValidationError('Payment and order totals do not reconcile.')
    total = format(payment.amount, '.2f')
    fields = {
        'amount': format(order.subtotal, '.2f'), 'tax_amount': '0',
        'product_service_charge': '0', 'product_delivery_charge': format(order.shipping_cost, '.2f'),
        'total_amount': total, 'transaction_uuid': str(payment.transaction_uuid),
        'product_code': settings.ESEWA_PRODUCT_CODE, 'signed_field_names': REQUEST_FIELDS,
        'success_url': settings.PUBLIC_BASE_URL + reverse('payments:esewa_success', args=[payment.transaction_uuid]),
        'failure_url': settings.PUBLIC_BASE_URL + reverse('payments:esewa_failure', args=[payment.transaction_uuid]),
    }
    fields['signature'] = signature(','.join(f'{name}={fields[name]}' for name in REQUEST_FIELDS.split(',')))
    return fields


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate response field')
        result[name] = value
    return result


def decode_response(encoded, payment):
    try:
        if not encoded or len(encoded) > 8192:
            raise ValueError
        data = json.loads(base64.b64decode(encoded, validate=True), parse_float=Decimal,
                          object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or data.get('signed_field_names') != RESPONSE_FIELDS:
            raise ValueError
        names = RESPONSE_FIELDS.split(',')
        if any(not isinstance(data[name], (str, int, Decimal)) or isinstance(data[name], bool) for name in names):
            raise ValueError
        expected = signature(','.join(f'{name}={data[name]}' for name in names))
        if not isinstance(data.get('signature'), str) or not hmac.compare_digest(expected, data['signature']):
            raise ValueError
        if (str(data['transaction_uuid']) != str(payment.transaction_uuid)
                or data['product_code'] != settings.ESEWA_PRODUCT_CODE
                or money(data['total_amount']) != payment.amount
                or data['status'] != 'COMPLETE' or not data['transaction_code']
                or len(str(data['transaction_code'])) > 100):
            raise ValueError
        return data
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
        raise ValidationError('Invalid eSewa response. No payment has been accepted.')


def status_response(payment):
    # Never use callback-supplied URLs, IDs, prices or credentials for this call.
    try:
        response = requests.get(settings.ESEWA_STATUS_URL, params={
            'product_code': settings.ESEWA_PRODUCT_CODE,
            'total_amount': format(payment.amount, '.2f'),
            'transaction_uuid': str(payment.transaction_uuid),
        }, timeout=10, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            return None
        data = response.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError):
        return None


def validate_status(data, payment):
    if not data or 'status' not in data:
        return None
    # Official docs show both pid/scd/totalAmount/refId and the newer names.
    values = {}
    for key, alias in [('transaction_uuid', 'pid'), ('product_code', 'scd'),
                       ('total_amount', 'totalAmount'), ('ref_id', 'refId')]:
        if key in data and alias in data and str(data[key]) != str(data[alias]):
            raise ValidationError('Conflicting eSewa status fields.')
        values[key] = data.get(key, data.get(alias))
    if (str(values['transaction_uuid']) != str(payment.transaction_uuid)
            or values['product_code'] != settings.ESEWA_PRODUCT_CODE
            or money(values['total_amount']) != payment.amount):
        raise ValidationError('eSewa status does not match this payment.')
    status = data['status']
    reference = values['ref_id']
    if status in ('COMPLETE', 'FULL_REFUND') and (not isinstance(reference, str) or not reference or len(reference) > 100):
        raise ValidationError('Missing eSewa transaction reference.')
    return status, reference or ''
