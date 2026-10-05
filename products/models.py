from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.text import slugify


def generate_slug(instance):
    """Generate a unique slug once; keep existing URLs stable after renaming."""
    field = instance._meta.get_field('slug')
    base = slugify(instance.name)[:field.max_length] or 'item'
    slug = base
    number = 2
    existing = type(instance).objects.exclude(pk=instance.pk)
    while existing.filter(slug=slug).exists():
        suffix = f'-{number}'
        slug = base[:field.max_length - len(suffix)] + suffix
        number += 1
    return slug


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Size(models.Model):
    name = models.CharField(max_length=20, unique=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


class Color(models.Model):
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7, blank=True, validators=[
        RegexValidator(r'^#[0-9a-fA-F]{6}$', 'Use a hex color such as #000000.'),
    ])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    image = models.ImageField(upload_to='products/', blank=True)
    is_active = models.BooleanField(default=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', 'name']
        constraints = [models.CheckConstraint(condition=models.Q(price__gte=0), name='product_price_nonnegative')]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/gallery/')
    alt_text = models.CharField(max_length=200, blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'pk']

    def __str__(self):
        return f'{self.product} image {self.display_order}'


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name='variants')
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name='variants')
    sku = models.CharField(max_length=100, unique=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__name', 'color__name', 'size__display_order', 'size__name']
        constraints = [models.UniqueConstraint(fields=['product', 'size', 'color'], name='unique_product_size_color')]

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    def __str__(self):
        return f'{self.product} / {self.color} / {self.size}'
