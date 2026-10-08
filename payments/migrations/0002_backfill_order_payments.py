from uuid import uuid4

from django.db import migrations


def backfill(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Payment = apps.get_model('payments', 'Payment')
    database = schema_editor.connection.alias
    Order.objects.using(database).filter(payment_method='COD', payment_status='PENDING').update(payment_status='UNPAID')
    for order in Order.objects.using(database).iterator():
        Payment.objects.using(database).create(order_id=order.pk, payment_method=order.payment_method,
            status=order.payment_status, amount=order.grand_total, transaction_uuid=uuid4())
    # Historical paid timestamps/references are unknown; never invent them.


class Migration(migrations.Migration):
    dependencies = [('payments', '0001_initial')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
