from django.db.models import F

from .models import Order


def lock_order(order_id):
    """Call inside atomic: acquire the writer before reading workflow state.

    PostgreSQL locks the row; SQLite serializes writers (or raises a busy error,
    which rolls back and may be retried). Do not read state before this write.
    """
    Order.objects.filter(pk=order_id).update(workflow_version=F("workflow_version") + 1)
    return Order.objects.select_for_update().get(pk=order_id)
