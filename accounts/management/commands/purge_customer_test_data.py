from collections import Counter

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.db.models.deletion import Collector
from django.utils import timezone

from cart.models import Cart, CartItem
from dashboard.models import StaffActivity
from inventory.models import InventoryTransaction
from orders.models import Order, OrderItem
from products.models import ProductVariant
from payments.models import Payment

User = get_user_model()
PROTECTED = Q(role__in=[User.Role.OWNER, User.Role.STAFF]) | Q(is_staff=True) | Q(is_superuser=True)
TEST_ORDER_NUMBERS = (
    'BRM-20261007-B6FEE3C4F7A84F8D',
    'BRM-20261007-71426BD06DB44D38',
    'BRM-20261007-4D3BE2B0FBBB4010',
    'BRM-20261007-CECD35E330FA49A1',
    'BRM-20261005-647BE3A50B274A59',
)


class Command(BaseCommand):
    help = 'Preview customer cleanup or the five explicitly listed test orders; --confirm deletes atomically.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Delete the previewed customer data.')
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument('--include-orphaned', action='store_true',
                            help='Also include orders with no existing customer; dry run unless --confirm is supplied.')
        modes.add_argument('--purge-test-orders', action='store_true',
                           help='Only remove the five allowlisted test orders, preserving all users and carts.')

    def customer_queryset(self):
        return User.objects.filter(role=User.Role.CUSTOMER, is_staff=False, is_superuser=False)

    def assert_safe(self, users):
        if any(u.role != User.Role.CUSTOMER or u.is_staff or u.is_superuser for u in users):
            raise CommandError('Protected user included: cleanup aborted.')

    @transaction.atomic
    def handle(self, *args, **options):
        confirmed = options['confirm']
        test_orders_only = options['purge_test_orders']
        if test_orders_only and options['include_orphaned']:
            raise CommandError('--purge-test-orders cannot be combined with --include-orphaned.')
        users = [] if test_orders_only else list(self.customer_queryset().select_for_update().order_by('pk'))
        self.assert_safe(users)
        ids = [u.pk for u in users]
        protected_ids = set(User.objects.filter(PROTECTED).values_list('pk', flat=True))
        if protected_ids.intersection(ids):
            raise CommandError('Protected user included: cleanup aborted.')
        order_scope = Q(order_number__in=TEST_ORDER_NUMBERS) if test_orders_only else Q(customer_id__in=ids)
        if options['include_orphaned']:
            order_scope |= Q(customer_exists=False)
        # A dangling non-NULL customer_id is also orphaned. Do not join to User:
        # an inner join would silently hide such legacy/inconsistent records.
        orders = list(Order.objects.select_for_update().annotate(
            customer_exists=Exists(User.objects.filter(pk=OuterRef('customer_id')))
        ).filter(order_scope).order_by('pk'))
        orphaned = [order for order in orders if not order.customer_exists]
        if not test_orders_only and any(order.customer_id in protected_ids for order in orders):
            raise CommandError('Protected user order included: cleanup aborted.')
        order_ids = [o.pk for o in orders]
        references = [o.order_number for o in orders]
        items = list(OrderItem.objects.select_for_update().filter(order_id__in=order_ids))
        records = list(InventoryTransaction.objects.select_for_update().filter(
            reference__in=references, transaction_type__in=['ORDER', 'RETURN']))
        expected = Counter()
        deductions = Counter()
        returns = Counter()
        for item in items:
            if item.variant_id is None:
                raise CommandError(f'Order {item.order_id} has a missing variant; cannot safely restore stock.')
            expected[(item.order_id, item.variant_id)] += item.quantity
        reference_ids = {o.order_number: o.pk for o in orders}
        for record in records:
            key = (reference_ids[record.reference], record.variant_id)
            if record.transaction_type == 'ORDER':
                if record.quantity >= 0:
                    raise CommandError('Invalid order deduction; cleanup aborted.')
                deductions[key] += -record.quantity
            else:
                if record.quantity <= 0:
                    raise CommandError('Invalid order return; cleanup aborted.')
                returns[key] += record.quantity
        # eSewa failure/retry cycles can legitimately deduct and return the
        # same items more than once. Restore only their outstanding net debit.
        released_orders = {order.pk for order in orders if order.payment_stock_released}
        if (set(expected) != set(deductions)
                or any(q > deductions[k] for k, q in returns.items())
                or any(deductions[k] < q or not 0 <= deductions[k] - returns[k] <= q
                       or (k[0] in released_orders and deductions[k] != returns[k])
                       for k, q in expected.items())):
            raise CommandError('Order items and inventory deductions/returns do not reconcile; cleanup aborted.')
        restore = Counter()
        for key, quantity in expected.items():
            restore[key[1]] += deductions[key] - returns[key]
        variants = {v.pk: v for v in ProductVariant.objects.select_for_update().filter(
            pk__in=restore).order_by('pk')}
        if set(variants) != set(restore):
            raise CommandError('Missing inventory variant; cleanup aborted.')
        activity = StaffActivity.objects.filter(
            Q(staff_id__in=ids) | Q(reference__in=references, action__in=[
                StaffActivity.Action.ORDER_STATUS, StaffActivity.Action.DELIVERY_STATUS,
                StaffActivity.Action.PAYMENT_STATUS]))
        carts = Cart.objects.filter(user_id__in=ids)
        social = SocialAccount.objects.filter(user_id__in=ids)
        emails = EmailAddress.objects.filter(user_id__in=ids)
        # Look up content types without get_for_model(), which could write during a dry run.
        user_type = ContentType.objects.filter(app_label=User._meta.app_label, model=User._meta.model_name)
        order_type = ContentType.objects.filter(app_label=Order._meta.app_label, model=Order._meta.model_name)
        admin_logs = LogEntry.objects.filter(
            Q(user_id__in=ids)
            | Q(content_type__in=user_type, object_id__in=[str(pk) for pk in ids])
            | Q(content_type__in=order_type, object_id__in=[str(pk) for pk in order_ids]))
        scope = 'only the five allowlisted test orders; all users and carts are preserved' if test_orders_only else 'ALL ordinary CUSTOMER accounts'
        self.stdout.write(f'CONFIRMED cleanup: {scope}' if confirmed else f'DRY RUN: no data will be changed. Scope: {scope}. Use --confirm to delete.')
        for user in users:
            self.stdout.write(f'Customer to delete: {user.username} | {user.email} | id={user.pk}')
        for order in orphaned:
            self.stdout.write(f'Orphaned order to delete: {order.order_number} | id={order.pk} | customer_id={order.customer_id}')
        if test_orders_only:
            for order in orders:
                self.stdout.write(f'Allowlisted test order to delete: {order.order_number} | id={order.pk} | customer_id={order.customer_id}')
            for number in sorted(set(TEST_ORDER_NUMBERS) - set(references)):
                self.stdout.write(f'Allowlisted test order not present (no action): {number}')
        for item in items:
            self.stdout.write(f'Order item: id={item.pk} | order_id={item.order_id} | variant_id={item.variant_id} | sku={item.sku} | quantity={item.quantity}')
        for record in records:
            self.stdout.write(f'Order inventory transaction: id={record.pk} | order={record.reference} | variant_id={record.variant_id} | {record.transaction_type} | quantity={record.quantity:+d}')
        for entry in activity.order_by('pk'):
            self.stdout.write(f'Activity to delete: id={entry.pk} | order={entry.reference} | action={entry.action} | staff_id={entry.staff_id}')
        for entry in admin_logs.order_by('pk'):
            self.stdout.write(f'Admin log to delete: id={entry.pk} | object_id={entry.object_id} | user_id={entry.user_id}')
        protected_carts = list(Cart.objects.select_for_update().filter(
            user_id__in=protected_ids).order_by('pk'))
        protected_cart_ids = {cart.pk for cart in protected_carts}
        protected_users = {user.pk: user for user in User.objects.filter(pk__in=protected_ids)}
        for user in protected_users.values():
            self.stdout.write(f'Protected user that will remain: {user.username} | role={user.role} | is_staff={user.is_staff} | is_superuser={user.is_superuser}')
        for cart in protected_carts:
            user = protected_users[cart.user_id]
            self.stdout.write(f'Protected cart that will remain: CART {cart.pk} | user_id={user.pk} | user={user.username} | role={user.role}')
        counts = {
            'CUSTOMER users': len(users), 'Carts': carts.count(),
            'Cart items': CartItem.objects.filter(cart__in=carts).count(),
            'Orders': len(orders), 'Orphaned orders': len(orphaned), 'Order items': len(items),
            'Payment attempts': Payment.objects.filter(order_id__in=order_ids).count(),
            'Social accounts': social.count(),
            'Social tokens': SocialToken.objects.filter(account__in=social).count(),
            'Email addresses': emails.count(),
            'Email confirmations': EmailConfirmation.objects.filter(email_address__in=emails).count(),
            'Related admin logs': admin_logs.count(),
            'Related activity': activity.count(), 'Order inventory records': len(records),
            'User group memberships': User.groups.through.objects.filter(user_id__in=ids).count(),
            'User permission assignments': User.user_permissions.through.objects.filter(user_id__in=ids).count(),
        }
        for label, count in counts.items():
            self.stdout.write(f'{label}: {count}')
        self.stdout.write(f'Protected OWNER/STAFF/admin users that will remain: {len(protected_ids)}')
        self.stdout.write('Inventory restoration (net of recorded order returns):')
        for pk, quantity in sorted(restore.items()):
            variant = variants[pk]
            self.stdout.write(f'{variant.sku} (variant {pk}): +{quantity}; {variant.stock_quantity} -> {variant.stock_quantity + quantity}')
        if confirmed:
            # Repeat safety validation immediately before mutations.
            self.assert_safe(list(User.objects.select_for_update().filter(pk__in=ids)))
            if test_orders_only and Order.objects.filter(pk__in=order_ids).exclude(order_number__in=TEST_ORDER_NUMBERS).exists():
                raise CommandError('Order outside the explicit test allowlist; cleanup aborted.')
            if not test_orders_only and Order.objects.filter(pk__in=order_ids, customer__in=User.objects.filter(PROTECTED)).exists():
                raise CommandError('Protected user order included: cleanup aborted.')
            for pk, quantity in sorted(restore.items()):
                variant = variants[pk]
                if quantity and ProductVariant.objects.filter(pk=pk, stock_quantity=variant.stock_quantity).update(
                        stock_quantity=variant.stock_quantity + quantity, updated_at=timezone.now()) != 1:
                    raise CommandError('Stock changed concurrently; cleanup rolled back.')
            activity.delete()
            admin_logs.delete()
            InventoryTransaction.objects.filter(pk__in=[r.pk for r in records]).delete()
            Order.objects.filter(pk__in=order_ids).delete()
            # Verify the actual cascade cannot include protected users or catalog/configuration.
            collector = Collector(using=User.objects.db)
            collector.collect(User.objects.filter(pk__in=ids))
            allowed = {User, Cart, CartItem, SocialAccount, SocialToken, EmailAddress,
                       EmailConfirmation, LogEntry, User.groups.through, User.user_permissions.through}
            models = set(collector.data) | {q.model for q in collector.fast_deletes}
            if models - allowed:
                raise CommandError('Unexpected deletion cascade; cleanup rolled back.')
            self.assert_safe(collector.data.get(User, []))
            collector.delete()
            if set(User.objects.filter(pk__in=protected_ids).values_list('pk', flat=True)) != protected_ids:
                raise CommandError('Protected user safety check failed; cleanup rolled back.')
            if set(Cart.objects.filter(pk__in=protected_cart_ids).values_list('pk', flat=True)) != protected_cart_ids:
                raise CommandError('Protected cart safety check failed; cleanup rolled back.')
            self.stdout.write('Cleanup complete. Restored inventory is listed above.')
        else:
            self.stdout.write('Inventory restoration above is a preview only.')
        self.stdout.write('Remaining users (current database): username | email | role | is_staff | is_superuser')
        for user in User.objects.order_by('pk'):
            self.stdout.write(f'{user.username} | {user.email} | {user.role} | {user.is_staff} | {user.is_superuser}')
        for label, queryset in [('orders', Order.objects.all()), ('carts', Cart.objects.all()),
                                ('SocialAccounts', SocialAccount.objects.all()),
                                ('customers', User.objects.filter(role=User.Role.CUSTOMER))]:
            self.stdout.write(f'Remaining {label}: {queryset.count()}')
