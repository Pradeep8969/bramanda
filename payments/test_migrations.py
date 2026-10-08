from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PaymentBackfillMigrationTests(TransactionTestCase):
    def test_existing_cod_orders_are_backfilled_without_inventing_paid_data(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('payments', None), ('orders', '0001_initial')])
            old_apps = executor.loader.project_state([('orders', '0001_initial')]).apps
            User = old_apps.get_model('accounts', 'User')
            Order = old_apps.get_model('orders', 'Order')
            owner = User.objects.create(username='legacyowner', role='OWNER', is_staff=True, is_superuser=True)
            values = {'customer_id': owner.pk, 'first_name': 'Owner', 'last_name': 'Test',
                'email': 'owner@example.com', 'phone_number': '9800000001', 'shipping_address': 'Kathmandu',
                'subtotal': 500, 'shipping_cost': 100, 'grand_total': 600, 'payment_method': 'COD'}
            unpaid = Order.objects.create(**values, payment_status='PENDING')
            paid = Order.objects.create(**values, payment_status='PAID')
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            NewOrder = apps.get_model('orders', 'Order')
            Payment = apps.get_model('payments', 'Payment')
            NewUser = apps.get_model('accounts', 'User')
            self.assertEqual(NewOrder.objects.get(pk=unpaid.pk).payment_status, 'UNPAID')
            self.assertEqual(Payment.objects.get(order_id=unpaid.pk).status, 'UNPAID')
            historical = Payment.objects.get(order_id=paid.pk)
            self.assertEqual(historical.status, 'PAID')
            self.assertEqual(historical.amount, 600)
            self.assertIsNone(historical.paid_at)
            self.assertEqual(historical.transaction_code, '')
            self.assertEqual(historical.provider_reference, '')
            self.assertTrue(NewUser.objects.get(pk=owner.pk).is_superuser)
        finally:
            MigrationExecutor(connection).migrate(latest)
