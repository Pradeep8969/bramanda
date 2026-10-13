from django.contrib.staticfiles import finders
from django.shortcuts import render
from django.templatetags.static import static

from products.views import prepare_products, storefront_products


def home(request):
    products = storefront_products()
    featured = list(products.filter(featured=True)[:4])
    if len(featured) < 4:
        featured += list(
            products.exclude(pk__in=[product.pk for product in featured])[
                : 4 - len(featured)
            ]
        )
    campaign_path = "images/home/hero-editorial.webp"
    return render(
        request,
        "home.html",
        {
            "featured_products": prepare_products(featured),
            "editorial_product": next(
                (product for product in featured if product.image), None
            ),
            "campaign_image": (
                static(campaign_path) if finders.find(campaign_path) else ""
            ),
        },
    )
