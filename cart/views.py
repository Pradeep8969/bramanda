from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone

from products.models import Product, ProductVariant
from .forms import AddToCartForm, QuantityForm, available_variants
from .models import Cart, CartItem


def item_queryset():
    return CartItem.objects.select_related('variant__product__category', 'variant__color', 'variant__size')


def stock_error(variant, quantity):
    if not available_variants().filter(pk=variant.pk).exists():
        return 'This size and color combination is no longer available. Please remove it or choose another.'
    if quantity > variant.stock_quantity:
        return f'Only {variant.stock_quantity} are currently available. Please lower the quantity.'
    return None


@login_required
def cart_detail(request):
    cart = Cart.objects.filter(user=request.user).prefetch_related(
        Prefetch('items', queryset=item_queryset())).first()
    items = list(cart.items.all()) if cart else []
    for item in items:
        v = item.variant
        active = v.is_active and v.product.is_active and v.product.category.is_active and v.color.is_active and v.size.is_active
        item.stock_warning = (
            'This combination is no longer available.' if not active or not v.stock_quantity
            else f'Only {v.stock_quantity} available; please lower the quantity.' if item.quantity > v.stock_quantity else ''
        )
    return render(request, 'cart/detail.html', {'cart': cart, 'items': items})


@require_POST
def add_item(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True, category__is_active=True)
    if not request.user.is_authenticated:
        return redirect_to_login(reverse('products:detail', args=[product.slug]))
    form = AddToCartForm(request.POST, product=product)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect('products:detail', slug=slug)
    # Lock the user's cart to serialize changes on databases supporting row locks.
    with transaction.atomic():
        cart, _ = Cart.objects.get_or_create(user=request.user)
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        variant = available_variants().select_for_update().filter(pk=form.cleaned_data['variant'].pk, product=product).first()
        if variant is None:
            messages.error(request, 'This combination is no longer available.')
            return redirect('products:detail', slug=slug)
        item = cart.items.filter(variant=variant).first()
        quantity = form.cleaned_data['quantity'] + (item.quantity if item else 0)
        if quantity > variant.stock_quantity:
            messages.error(request, f'Only {variant.stock_quantity} are available, including items already in your cart.')
            return redirect('products:detail', slug=slug)
        if item:
            item.quantity = quantity
            item.save(update_fields=['quantity', 'updated_at'])
        else:
            CartItem.objects.create(cart=cart, variant=variant, quantity=quantity)
        cart.updated_at = timezone.now()
        cart.save(update_fields=['updated_at'])
    messages.success(request, f'{product.name} added to your cart.')
    return redirect('cart:detail')


@require_POST
@login_required
def update_item(request, item_id):
    form = QuantityForm(request.POST)
    with transaction.atomic():
        cart = get_object_or_404(Cart.objects.select_for_update(), user=request.user)
        item = get_object_or_404(item_queryset(), pk=item_id, cart=cart)
        if not form.is_valid():
            messages.error(request, 'Enter a whole-number quantity of at least 1.')
        else:
            variant = ProductVariant.objects.select_for_update().get(pk=item.variant_id)
            error = stock_error(variant, form.cleaned_data['quantity'])
            if error:
                messages.error(request, error)
            else:
                item.quantity = form.cleaned_data['quantity']
                item.save(update_fields=['quantity', 'updated_at'])
                cart.updated_at = timezone.now()
                cart.save(update_fields=['updated_at'])
                messages.success(request, 'Cart quantity updated.')
    return redirect('cart:detail')


@require_POST
@login_required
def remove_item(request, item_id):
    with transaction.atomic():
        cart = get_object_or_404(Cart.objects.select_for_update(), user=request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        item.delete()
        cart.updated_at = timezone.now()
        cart.save(update_fields=['updated_at'])
    messages.success(request, 'Item removed from your cart.')
    return redirect('cart:detail')

