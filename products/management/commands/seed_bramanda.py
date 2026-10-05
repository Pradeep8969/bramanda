from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import InventoryTransaction
from inventory.services import adjust_stock
from products.models import Category, Color, Product, ProductVariant, Size


class Command(BaseCommand):
    help = 'Create Bramanda sample products and variants without overwriting existing data.'

    @transaction.atomic
    def handle(self, *args, **options):
        category, _ = Category.objects.get_or_create(name='T-Shirts')
        sizes = []
        for order, name in enumerate(('S', 'M', 'L', 'XL'), start=1):
            size, _ = Size.objects.get_or_create(name=name, defaults={'display_order': order})
            sizes.append(size)
        product, product_created = Product.objects.get_or_create(
            slug='bramanda-oversized-t-shirt',
            defaults={'name': 'Bramanda Oversized T-Shirt', 'category': category,
                      'description': 'A comfortable oversized T-shirt by Bramanda.', 'price': Decimal('845.00')},
        )
        created_count = 0
        samples = (
            ('Black', '#000000', 'BLK', (10, 20, 12, 8)),
            ('Beige', '#F5F5DC', 'BEI', (7, 15, 10, 6)),
            ('Bottle Green', '#006A4E', 'GRN', (8, 11, 9, 5)),
        )
        for name, hex_code, code, stocks in samples:
            color, _ = Color.objects.get_or_create(name=name, defaults={'hex_code': hex_code})
            for size, stock in zip(sizes, stocks):
                variant, created = ProductVariant.objects.get_or_create(
                    product=product, size=size, color=color,
                    defaults={'sku': f'BRM-OTS-{code}-{size.name}'},
                )
                if created:
                    adjust_stock(variant, stock, InventoryTransaction.TransactionType.STOCK_IN,
                                 reference='seed_bramanda', note='Initial sample stock.')
                    created_count += 1
        self.stdout.write(self.style.SUCCESS(
            f'Sample product {"created" if product_created else "already exists"}; '
            f'{created_count} variants created; {product.variants.count()} variants total.'
        ))
