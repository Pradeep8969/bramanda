from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cart.models import Cart, CartItem
from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from products.models import ProductVariant
from .forms import CheckoutForm
from .models import Order, OrderItem

# One fixed delivery fee for the college version.
SHIPPING_COST = Decimal('100.00')


@transaction.atomic
def create_order_from_cart(user, cart, checkout_data):
    """Snapshot a validated cart and debit inventory as one all-or-nothing operation."""
    if not user.is_authenticated or cart.user_id != user.pk:
        raise ValidationError('This cart does not belong to your account.')
    cart = Cart.objects.select_for_update().get(pk=cart.pk, user=user)
    items = list(CartItem.objects.select_for_update().filter(cart=cart).order_by('variant_id'))
    if not items:
        raise ValidationError('Your cart is empty. Please add products before checking out.')
    form = CheckoutForm(checkout_data)
    if not form.is_valid():
        raise ValidationError([error for errors in form.errors.values() for error in errors])

    # Lock in a stable order; use current database stock and prices, never cached cart objects.
    variants = ProductVariant.objects.select_for_update().filter(
        pk__in=[item.variant_id for item in items],
    ).select_related('product__category', 'size', 'color').order_by('pk')
    variants = {variant.pk: variant for variant in variants}
    subtotal = Decimal('0.00')
    for item in items:
        variant = variants.get(item.variant_id)
        if variant is None:
            raise ValidationError('A cart item is no longer available. Please update your cart.')
        product = variant.product
        if not all((variant.is_active, product.is_active, product.category.is_active, variant.size.is_active, variant.color.is_active)):
            raise ValidationError(f'{product.name} / {variant.color.name} / {variant.size.name} is no longer available. Please update your cart.')
        if item.quantity < 1:
            raise ValidationError('Cart quantities must be at least 1.')
        if variant.stock_quantity < item.quantity:
            raise ValidationError(f'Only {variant.stock_quantity} item(s) are currently available for {variant.color.name} / {variant.size.name}. Please update your cart.')
        subtotal += product.price * item.quantity

    order = Order.objects.create(
        customer=user, subtotal=subtotal, shipping_cost=SHIPPING_COST,
        grand_total=subtotal + SHIPPING_COST, **form.cleaned_data,
    )
    for item in items:
        variant = variants[item.variant_id]
        product = variant.product
        OrderItem.objects.create(
            order=order, product=product, variant=variant, product_name=product.name,
            size_name=variant.size.name, color_name=variant.color.name, sku=variant.sku,
            quantity=item.quantity, unit_price=product.price, subtotal=product.price * item.quantity,
        )
        # Existing service includes a conditional stock update for SQLite safety.
        adjust_stock(variant, -item.quantity, InventoryTransaction.TransactionType.ORDER,
                     user=user, reference=order.order_number)
    CartItem.objects.filter(cart=cart).delete()
    cart.updated_at = timezone.now()
    cart.save(update_fields=['updated_at'])
    return order

