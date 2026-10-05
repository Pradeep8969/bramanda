from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, render

from .models import Category, Color, Product, ProductVariant, Size
from cart.forms import AddToCartForm


def active_variants():
    return ProductVariant.objects.filter(is_active=True, color__is_active=True, size__is_active=True).select_related('color', 'size')


def storefront_products():
    return Product.objects.filter(is_active=True, category__is_active=True).select_related('category').prefetch_related(
        Prefetch('variants', queryset=active_variants(), to_attr='storefront_variants'))


def prepare_products(products):
    for product in products:
        product.available = any(v.stock_quantity > 0 for v in product.storefront_variants)
    return products


def shop(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    color = request.GET.get('color', '').strip()
    size = request.GET.get('size', '').strip()
    sort = request.GET.get('sort', 'newest')
    ordering = {'newest': ('-created_at', '-pk'), 'price_asc': ('price', 'name', 'pk'),
                'price_desc': ('-price', 'name', 'pk'), 'name': ('name', 'pk')}
    if sort not in ordering:
        sort = 'newest'
    products = storefront_products()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(category__name__icontains=query))
    if category:
        products = products.filter(category__slug=category)
    # Color and size must match the same active combination.
    if color or size:
        variants = active_variants()
        if color:
            variants = variants.filter(color__name__iexact=color)
        if size:
            variants = variants.filter(size__name__iexact=size)
        products = products.filter(variants__in=variants).distinct()
    return render(request, 'products/shop.html', {
        'products': prepare_products(list(products.order_by(*ordering[sort]))),
        'categories': Category.objects.filter(is_active=True), 'colors': Color.objects.filter(is_active=True),
        'sizes': Size.objects.filter(is_active=True), 'q': query, 'selected_category': category,
        'selected_color': color, 'selected_size': size, 'sort': sort,
    })


def product_detail(request, slug):
    product = get_object_or_404(storefront_products().prefetch_related('images'), slug=slug)
    prepare_products([product])
    groups = {}
    for variant in product.storefront_variants:
        groups.setdefault(variant.color.name, []).append({'size': variant.size.name, 'stock': variant.stock_quantity})
    return render(request, 'products/detail.html', {
        'product': product, 'variant_groups': groups, 'cart_form': AddToCartForm(product=product),
    })
