from django.shortcuts import render
from products.views import prepare_products, storefront_products


def home(request):
    products = storefront_products()
    featured = list(products.filter(featured=True)[:4])
    if not featured:
        featured = list(products[:4])
    return render(request, 'home.html', {'featured_products': prepare_products(featured)})
