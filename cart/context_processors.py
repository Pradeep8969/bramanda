from django.db.models import Sum
from .models import CartItem


def cart_counter(request):
    if not request.user.is_authenticated:
        return {'cart_count': 0}
    count = CartItem.objects.filter(cart__user=request.user).aggregate(total=Sum('quantity'))['total']
    return {'cart_count': count or 0}

