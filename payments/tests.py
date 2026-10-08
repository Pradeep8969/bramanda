import base64
import json
from decimal import Decimal
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from cart.models import Cart, CartItem
from dashboard.models import StaffActivity
from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from orders.models import Order
from orders.services import create_order_from_cart
from products.models import Category, Product, ProductVariant, Size, Color
from . import esewa
from .models import Payment
from .services import retry_esewa, verify_payment


class PaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer', email='buyer@example.com')
        self.other = User.objects.create_user(username='other')
        self.staff = User.objects.create_user(username='staff', role='STAFF')
        self.owner = User.objects.create_user(username='owner', role='OWNER')
        product = Product.objects.create(name='Shirt', category=Category.objects.create(name='Clothes'), price=250)
        self.variant = ProductVariant.objects.create(product=product, size=Size.objects.create(name='M'),
            color=Color.objects.create(name='Black'), sku='PAY-M', stock_quantity=10)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, variant=self.variant, quantity=2)
        self.client.force_login(self.user)
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Payment tests must not contact eSewa'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def checkout_data(self, method='ESEWA'):
        return {'first_name': 'Asha', 'last_name': 'Rai', 'email': self.user.email,
                'phone_number': '9800000001', 'shipping_address': 'Kathmandu', 'payment_method': method}

    def place(self, method='ESEWA'):
        self.order = create_order_from_cart(self.user, self.cart, self.checkout_data(method))
        self.payment = self.order.latest_payment
        return self.order

    def url(self, name, payment=None):
        return reverse('payments:' + name, args=[(payment or self.payment).transaction_uuid])

    def document_url(self, name):
        return reverse('payments:' + name, args=[self.order.order_number])

    def provider_status(self, status='COMPLETE', payment=None, **changes):
        payment = payment or self.payment
        data = {'status': status, 'pid': str(payment.transaction_uuid), 'scd': 'EPAYTEST',
                'totalAmount': str(payment.amount), 'refId': 'UAT-REFERENCE-123' if status == 'COMPLETE' else None}
        data.update(changes)
        return data

    def callback(self, payment=None, **changes):
        payment = payment or self.payment
        data = {'transaction_code': 'UAT-REFERENCE-123', 'status': 'COMPLETE',
                'total_amount': str(payment.amount), 'transaction_uuid': str(payment.transaction_uuid),
                'product_code': 'EPAYTEST', 'signed_field_names': esewa.RESPONSE_FIELDS}
        data.update(changes)
        data['signature'] = esewa.signature(','.join(f'{name}={data[name]}' for name in data['signed_field_names'].split(',')))
        return base64.b64encode(json.dumps(data).encode()).decode()

    def verify(self, status='COMPLETE', payment=None, **changes):
        payment = payment or self.payment
        with patch('payments.esewa.status_response', return_value=self.provider_status(status, payment, **changes)):
            return verify_payment(payment.pk)

    def assert_stock(self, quantity):
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, quantity)

    def test_cod_checkout_unpaid_invoice_amount_due_and_no_receipt(self):
        response = self.client.post('/checkout/', self.checkout_data('COD'))
        self.order = Order.objects.get()
        self.payment = self.order.latest_payment
        self.assertRedirects(response, reverse('orders:success', args=[self.order.order_number]))
        self.assertEqual(self.order.order_status, 'CONFIRMED')
        self.assertEqual(self.order.payment_status, 'UNPAID')
        self.assertEqual(self.payment.status, 'UNPAID')
        self.assertIsNone(self.payment.paid_at)
        self.assertEqual(self.payment.transaction_code, '')
        self.assert_stock(8)
        invoice = self.client.get(self.document_url('invoice'))
        self.assertContains(invoice, 'Order Confirmation / Invoice')
        self.assertContains(invoice, 'Amount Due')
        self.assertContains(invoice, '600.00')
        self.assertNotContains(invoice, 'Amount Paid')
        self.assertNotContains(invoice, str(self.payment.transaction_uuid))
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)

    def test_authorized_cod_collection_creates_paid_receipt_once(self):
        self.place('COD')
        for operator, namespace in [(self.staff, 'dashboard'), (self.owner, 'owner')]:
            self.client.force_login(operator)
            response = self.client.post(reverse(namespace + ':payment_status', args=[self.order.order_number]), {'payment_status': 'PAID'})
            self.assertEqual(response.status_code, 302)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assertIsNotNone(self.payment.paid_at)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(StaffActivity.objects.filter(action='PAYMENT_STATUS').count(), 1)
        receipt = self.client.get(self.document_url('receipt'))
        self.assertContains(receipt, 'Payment Receipt')
        self.assertContains(receipt, 'Amount Paid')
        self.assertContains(receipt, 'Print Receipt')
        self.assertNotContains(receipt, 'Amount Due')
        self.assertNotContains(receipt, 'eSewa transaction')

    def test_customer_cannot_mark_cod_paid(self):
        self.place('COD')
        for namespace in ('dashboard', 'owner'):
            self.assertEqual(self.client.post(reverse(namespace + ':payment_status', args=[self.order.order_number]),
                {'payment_status': 'PAID'}).status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'UNPAID')

    def test_esewa_checkout_redirect_pending_and_server_totals(self):
        data = self.checkout_data()
        data.update(total_amount='1', amount='1', payment_status='PAID', product_delivery_charge='0')
        response = self.client.post('/checkout/', data)
        self.order = Order.objects.get()
        self.payment = self.order.latest_payment
        self.assertRedirects(response, self.url('pay'))
        self.assertEqual(self.order.order_status, 'PENDING')
        self.assertEqual(self.payment.status, 'PENDING')
        self.assertEqual(self.payment.amount, Decimal('600.00'))
        fields = self.client.get(self.url('pay')).context['fields']
        self.assertEqual(fields['amount'], '500.00')
        self.assertEqual(fields['product_delivery_charge'], '100.00')
        self.assertEqual(fields['total_amount'], '600.00')
        self.assertEqual(fields['tax_amount'], '0')
        self.assertEqual(fields['product_service_charge'], '0')
        self.assertEqual(fields['signed_field_names'], esewa.REQUEST_FIELDS)
        self.assertTrue(fields['success_url'].startswith(settings.PUBLIC_BASE_URL))
        self.assert_stock(8)

    def test_hmac_sha256_against_rfc4231_vector(self):
        # RFC 4231 section 4.3 independently specifies this digest.
        expected = bytes.fromhex('5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843')
        with self.settings(ESEWA_SECRET_KEY='Jefe'):
            self.assertEqual(esewa.signature('what do ya want for nothing?'), base64.b64encode(expected).decode())

    def test_signature_on_actual_server_form(self):
        self.place()
        fields = esewa.form_fields(self.payment)
        self.assertEqual(fields['signature'], esewa.signature(
            f'total_amount=600.00,transaction_uuid={self.payment.transaction_uuid},product_code=EPAYTEST'))

    def test_verified_complete_callback_marks_paid_receipt_and_duplicate_is_idempotent(self):
        self.place()
        encoded = self.callback()
        with patch('payments.esewa.status_response', return_value=self.provider_status()) as verification:
            self.assertRedirects(self.client.get(self.url('esewa_success'), {'data': encoded}), self.url('result'))
            self.payment.refresh_from_db()
            paid_at = self.payment.paid_at
            self.assertIsNotNone(paid_at)
            self.assertRedirects(self.client.get(self.url('esewa_success'), {'data': encoded}), self.url('result'))
            self.assertEqual(verification.call_count, 2)
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.order.order_status, 'CONFIRMED')
        self.assertEqual(self.payment.paid_at, paid_at)
        self.assertEqual(self.payment.transaction_code, 'UAT-REFERENCE-123')
        self.assertEqual(self.payment.provider_reference, 'UAT-REFERENCE-123')
        self.assertEqual(Payment.objects.count(), 1)
        self.assert_stock(8)
        self.assertEqual(InventoryTransaction.objects.count(), 1)
        self.assertContains(self.client.get(self.document_url('receipt')), 'UAT-REFERENCE-123')

    def test_success_without_session_still_verifies_but_receipt_requires_login(self):
        self.place()
        self.client.logout()
        with patch('payments.esewa.status_response', return_value=self.provider_status()):
            self.assertEqual(self.client.get(self.url('esewa_success'), {'data': self.callback()}).status_code, 302)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 302)

    def test_invalid_signature_is_rejected_before_http_verification(self):
        self.place()
        data = json.loads(base64.b64decode(self.callback()))
        data['signature'] = 'invalid'
        with patch('payments.esewa.status_response') as verification:
            self.assertEqual(self.client.get(self.url('esewa_success'),
                {'data': base64.b64encode(json.dumps(data).encode()).decode()}).status_code, 400)
            verification.assert_not_called()
        self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_altered_amount_is_rejected_even_with_valid_signature(self):
        self.place()
        with patch('payments.esewa.status_response') as verification:
            self.assertEqual(self.client.get(self.url('esewa_success'), {'data': self.callback(total_amount='1.00')}).status_code, 400)
            verification.assert_not_called()
        self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_wrong_uuid_and_product_code_are_rejected(self):
        self.place()
        for changes in ({'transaction_uuid': str(uuid4())}, {'product_code': 'wrong'}):
            with patch('payments.esewa.status_response') as verification:
                self.assertEqual(self.client.get(self.url('esewa_success'), {'data': self.callback(**changes)}).status_code, 400)
                verification.assert_not_called()
        self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_missing_signed_amount_field_is_rejected(self):
        self.place()
        data = self.callback(signed_field_names='transaction_code,status,transaction_uuid,product_code,signed_field_names')
        self.assertEqual(self.client.get(self.url('esewa_success'), {'data': data}).status_code, 400)

    def test_manually_opening_success_url_cannot_mark_paid(self):
        self.place()
        for encoded in (None, 'not-base64', 'e30='):
            with patch('payments.esewa.status_response') as verification:
                self.assertEqual(self.client.get(self.url('esewa_success'), {'data': encoded} if encoded else {}).status_code, 400)
                verification.assert_not_called()
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assert_stock(8)

    def test_valid_callback_with_pending_provider_status_stays_pending(self):
        self.place()
        with patch('payments.esewa.status_response', return_value=self.provider_status('PENDING')):
            self.client.get(self.url('esewa_success'), {'data': self.callback()})
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)

    def test_status_uuid_amount_product_or_reference_mismatch_cannot_mark_paid(self):
        self.place()
        for changes in ({'pid': str(uuid4())}, {'totalAmount': '1'}, {'scd': 'wrong'}, {'refId': 'different'}):
            with patch('payments.esewa.status_response', return_value=self.provider_status(**changes)):
                self.assertEqual(self.client.get(self.url('esewa_success'), {'data': self.callback()}).status_code, 400)
            self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_missing_reference_cannot_mark_paid(self):
        self.place()
        with self.assertRaises(ValidationError):
            self.verify(refId=None)
        self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_status_request_uses_fixed_uat_url_server_amount_uuid_and_timeout(self):
        self.place()
        with patch('payments.esewa.requests.get') as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = self.provider_status()
            verify_payment(self.payment.pk)
            get.assert_called_once_with(settings.ESEWA_STATUS_URL, params={
                'product_code': 'EPAYTEST', 'total_amount': '600.00',
                'transaction_uuid': str(self.payment.transaction_uuid)}, timeout=10, allow_redirects=False)
        self.assertEqual(Payment.objects.get().status, 'PAID')

    def test_http_timeout_invalid_json_or_provider_unavailable_keeps_pending(self):
        self.place()
        with patch('payments.esewa.requests.get', side_effect=requests.Timeout):
            verify_payment(self.payment.pk)
        with patch('payments.esewa.requests.get') as get:
            get.return_value.status_code = 200
            get.return_value.json.side_effect = ValueError('Invalid JSON')
            verify_payment(self.payment.pk)
        with patch('payments.esewa.status_response', return_value={'code': 0, 'error_message': 'Unavailable'}):
            verify_payment(self.payment.pk)
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assert_stock(8)

    def test_failed_payment_releases_stock_once_and_never_has_receipt(self):
        self.place()
        self.verify('FAILED')
        self.verify('FAILED')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'FAILED')
        self.assertEqual(self.order.order_status, 'CANCELLED')
        self.assertTrue(self.order.payment_stock_released)
        self.assert_stock(10)
        self.assertEqual(InventoryTransaction.objects.filter(transaction_type='RETURN').count(), 1)
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)
        self.assertContains(self.client.get(reverse('orders:detail', args=[self.order.order_number])), 'Retry eSewa Payment')

    def test_cancelled_payment_releases_stock_and_remains_unpaid(self):
        self.place()
        self.verify('CANCELED')
        self.assertEqual(Payment.objects.get().status, 'CANCELLED')
        self.assert_stock(10)
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)

    def test_not_found_releases_stock_only_after_verified_status(self):
        self.place()
        self.verify('NOT_FOUND')
        self.assertEqual(Payment.objects.get().status, 'FAILED')
        self.assert_stock(10)

    def test_pending_and_ambiguous_do_not_release_or_create_receipt(self):
        self.place()
        for status in ('PENDING', 'AMBIGUOUS', 'AMBIGIOUS', 'UNKNOWN', 'PARTIAL_REFUND'):
            self.verify(status)
            self.assertEqual(Payment.objects.get().status, 'PENDING')
            self.assert_stock(8)
            self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)

    def test_unsigned_failure_redirect_does_not_trust_browser(self):
        self.place()
        with patch('payments.esewa.status_response', return_value=self.provider_status('PENDING')):
            self.client.get(self.url('esewa_failure'), {'status': 'CANCELLED'})
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assert_stock(8)

    def test_retry_creates_new_attempt_and_reserves_stock_once(self):
        self.place()
        self.verify('FAILED')
        response = self.client.post(self.document_url('retry'))
        new = self.order.latest_payment
        self.assertRedirects(response, self.url('pay', new))
        self.assertNotEqual(self.payment.transaction_uuid, new.transaction_uuid)
        self.assertEqual(self.order.payments.count(), 2)
        self.assertEqual(new.status, 'PENDING')
        self.assert_stock(8)
        self.client.post(self.document_url('retry'))
        self.assertEqual(self.order.payments.count(), 2)
        self.assert_stock(8)
        self.verify('FAILED', payment=self.payment)  # Old failures cannot cancel/release a retry.
        self.assertEqual(Payment.objects.get(pk=new.pk).status, 'PENDING')
        self.assert_stock(8)
        self.verify(payment=new)
        self.assert_stock(8)

    def test_retry_with_insufficient_stock_rolls_back_new_attempt(self):
        self.place()
        self.verify('FAILED')
        adjust_stock(self.variant, -9, 'ADJUSTMENT', user=self.owner, reference='MANUAL')
        with self.assertRaises(ValidationError):
            retry_esewa(self.order.pk)
        self.assertEqual(self.order.payments.count(), 1)
        self.assert_stock(1)
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_stock_released)

    def test_pending_attempt_cannot_be_retried(self):
        self.place()
        with self.assertRaises(ValidationError):
            retry_esewa(self.order.pk)
        self.assertEqual(Payment.objects.count(), 1)
        self.assert_stock(8)

    def test_staff_cannot_fake_esewa_collection_or_fulfill_unpaid_order(self):
        self.place()
        self.client.force_login(self.staff)
        for route, data in [('payment_status', {'payment_status': 'PAID'}),
                            ('order_status', {'order_status': 'PROCESSING'}),
                            ('delivery_status', {'delivery_status': 'SHIPPED'})]:
            self.assertEqual(self.client.post(reverse('dashboard:' + route, args=[self.order.order_number]), data).status_code, 400)
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assertFalse(StaffActivity.objects.exists())

    def test_staff_can_recheck_but_customer_cannot_access_other_customers_payments(self):
        self.place()
        self.client.force_login(self.staff)
        with patch('payments.esewa.status_response', return_value=self.provider_status()):
            self.assertRedirects(self.client.post(self.url('recheck')),
                                 reverse('dashboard:order_detail', args=[self.order.order_number]))
        self.client.force_login(self.other)
        for route in ('pay', 'result', 'recheck'):
            response = self.client.post(self.url(route)) if route == 'recheck' else self.client.get(self.url(route))
            self.assertEqual(response.status_code, 404)
        for name in ('invoice', 'receipt', 'retry'):
            response = self.client.post(self.document_url(name)) if name == 'retry' else self.client.get(self.document_url(name))
            self.assertEqual(response.status_code, 404)

    def test_retry_and_recheck_require_csrf_and_post(self):
        self.place()
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        for url in (self.document_url('retry'), self.url('recheck')):
            self.assertEqual(secure.get(url).status_code, 405)
            self.assertEqual(secure.post(url).status_code, 403)

    def test_failure_reconciliation_with_missing_inventory_rolls_back(self):
        self.place()
        InventoryTransaction.objects.all().delete()
        with self.assertRaises(ValidationError):
            self.verify('FAILED')
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assert_stock(8)

    def test_late_verified_payment_after_release_records_funds_and_reserves_once(self):
        self.place()
        self.verify('FAILED')
        self.verify()
        self.assertEqual(Payment.objects.get().status, 'PAID')
        self.assert_stock(8)
        self.verify()
        self.assert_stock(8)

    def test_late_payment_after_stock_sold_records_paid_but_blocks_fulfillment(self):
        self.place()
        self.verify('FAILED')
        adjust_stock(self.variant, -9, 'ADJUSTMENT', user=self.owner, reference='MANUAL')
        self.verify()
        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, 'PAID')
        self.assertTrue(self.payment.review_required)
        self.assertTrue(self.order.payment_stock_released)
        self.assertEqual(self.order.order_status, 'CANCELLED')
        self.assert_stock(1)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(reverse('dashboard:order_status', args=[self.order.order_number]),
            {'order_status': 'PROCESSING'}).status_code, 400)

    def test_late_old_success_then_retry_success_records_both_without_double_stock(self):
        self.place()
        self.verify('FAILED')
        new = retry_esewa(self.order.pk)
        self.verify()
        self.verify(payment=new, refId='SECOND-PAID-REFERENCE')
        self.assertEqual(self.order.payments.filter(status='PAID').count(), 2)
        new.refresh_from_db()
        self.assertTrue(new.review_required)
        self.assert_stock(8)
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 200)

    def test_failure_of_retry_cannot_release_stock_after_old_attempt_paid(self):
        self.place()
        self.verify('FAILED')
        new = retry_esewa(self.order.pk)
        self.verify()
        self.verify('FAILED', payment=new)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'PAID')
        self.assert_stock(8)

    def test_full_refund_has_no_paid_receipt_or_automatic_stock_return(self):
        self.place()
        self.verify()
        self.verify('FULL_REFUND', refId='UAT-REFERENCE-123')
        self.assertEqual(Payment.objects.get().status, 'REFUNDED')
        self.assertEqual(self.client.get(self.document_url('receipt')).status_code, 404)
        self.assert_stock(8)

    def test_reconciliation_command_processes_abandoned_pending_attempt(self):
        self.place()
        with patch('payments.esewa.status_response', return_value=self.provider_status('NOT_FOUND')):
            call_command('reconcile_esewa_payments', stdout=StringIO())
        self.assertEqual(Payment.objects.get().status, 'FAILED')
        self.assert_stock(10)

    def test_owner_reports_exclude_unpaid_and_failed_revenue(self):
        self.place()
        self.client.force_login(self.owner)
        response = self.client.get('/owner/payments/')
        summary = dict(response.context['payment_summary'])
        self.assertEqual(summary['Paid revenue'], 0)
        self.assertEqual(summary['Pending eSewa'], Decimal('600.00'))
        self.verify('FAILED')
        summary = dict(self.client.get('/owner/reports/').context['payment_summary'])
        self.assertEqual(summary['Paid revenue'], 0)
        self.assertEqual(summary['Failed/cancelled payments'], Decimal('600.00'))

    def test_database_prevents_two_pending_attempts(self):
        self.place()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.create(order=self.order, status='PENDING', payment_method='ESEWA', amount=600)

    def test_empty_uat_key_rolls_back_checkout_stock_cart_and_order(self):
        with self.settings(ESEWA_SECRET_KEY=''):
            with self.assertRaises(ValidationError):
                self.place()
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(CartItem.objects.count(), 1)
        self.assert_stock(10)

    def test_signed_form_rejects_changed_order_total(self):
        self.place()
        self.order.grand_total = Decimal('1')
        self.payment.order = self.order
        with self.assertRaises(ValidationError):
            esewa.form_fields(self.payment)

    def test_new_status_field_names_are_supported(self):
        self.place()
        payload = {'status': 'COMPLETE', 'transaction_uuid': str(self.payment.transaction_uuid),
                   'product_code': 'EPAYTEST', 'total_amount': '600.00', 'ref_id': 'UAT-REFERENCE-123'}
        with patch('payments.esewa.status_response', return_value=payload):
            verify_payment(self.payment.pk)
        self.assertEqual(Payment.objects.get().status, 'PAID')

    def test_conflicting_status_aliases_are_rejected(self):
        self.place()
        with self.assertRaises(ValidationError):
            self.verify(transaction_uuid=str(uuid4()))
        self.assertEqual(Payment.objects.get().status, 'PENDING')

    def test_database_failure_rolls_back_failed_payment_and_stock_return(self):
        self.place()
        with patch('payments.models.Payment.save', side_effect=IntegrityError('Failed save')):
            with self.assertRaises(IntegrityError):
                self.verify('FAILED')
        self.assertEqual(Payment.objects.get().status, 'PENDING')
        self.assertEqual(InventoryTransaction.objects.count(), 1)
        self.assert_stock(8)

    def test_retry_cannot_double_deduct_after_second_failed_attempt(self):
        self.place()
        self.verify('FAILED')
        new = retry_esewa(self.order.pk)
        self.verify('FAILED', payment=new)
        self.verify('FAILED', payment=new)
        self.assert_stock(10)
        third = retry_esewa(self.order.pk)
        self.assert_stock(8)
        self.verify(payment=third)
        self.assert_stock(8)
        self.assertEqual(self.order.payments.count(), 3)

    def test_cleanup_preview_reconciles_retry_history_without_mutating_data(self):
        self.place()
        self.verify('FAILED')
        retry_esewa(self.order.pk)
        out = StringIO()
        call_command('purge_customer_test_data', stdout=out)
        self.assertIn('+2; 8 -> 10', out.getvalue())
        self.assertIn('Payment attempts: 2', out.getvalue())
        self.assert_stock(8)
        self.assertEqual(self.order.payments.count(), 2)

    def test_admin_cannot_edit_payment_status_without_verification(self):
        from django.contrib import admin
        self.assertIn('payment_status', admin.site._registry[Order].readonly_fields)
        self.assertIn('status', admin.site._registry[Payment].readonly_fields)
