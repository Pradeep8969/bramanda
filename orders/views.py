from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from cart.models import Cart
from cart.views import item_queryset
from .forms import CheckoutForm
from .models import Order
from .services import SHIPPING_COST, create_order_from_cart


@login_required
@require_http_methods(['GET', 'POST'])
def checkout(request):
    cart = Cart.objects.filter(user=request.user).prefetch_related(Prefetch('items', queryset=item_queryset())).first()
    if cart is None or not cart.items.all():
        messages.info(request, 'Your cart is empty. Add a product before checking out.')
        return redirect('cart:detail')
    user = request.user
    initial = {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
               'phone_number': user.phone_number, 'shipping_address': user.address}
    form = CheckoutForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            order = create_order_from_cart(user, cart, form.cleaned_data)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
        except DatabaseError:
            # A SQLite writer conflict rolls back the entire service transaction.
            form.add_error(None, 'Your cart or stock changed while placing the order. Please try again.')
        else:
            messages.success(request, 'Thank you! Your order has been confirmed.')
            return redirect('orders:success', order_number=order.order_number)
    subtotal = cart.subtotal
    return render(request, 'orders/checkout.html', {'form': form, 'cart': cart, 'items': cart.items.all(),
                  'subtotal': subtotal, 'shipping_cost': SHIPPING_COST, 'grand_total': subtotal + SHIPPING_COST})


@login_required
@require_safe
def order_list(request):
    return render(request, 'orders/list.html', {'orders': Order.objects.filter(customer=request.user)})


@login_required
@require_safe
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.filter(customer=request.user).prefetch_related('items'), order_number=order_number)
    return render(request, 'orders/detail.html', {'order': order})


@login_required
@require_safe
def order_success(request, order_number):
    order = get_object_or_404(Order, customer=request.user, order_number=order_number)
    return render(request, 'orders/success.html', {'order': order})

