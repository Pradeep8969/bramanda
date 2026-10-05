from django import forms

from .models import Category, Color, Product, ProductVariant, Size


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'slug', 'description', 'is_active')


class SizeForm(forms.ModelForm):
    class Meta:
        model = Size
        fields = ('name', 'display_order', 'is_active')


class ColorForm(forms.ModelForm):
    class Meta:
        model = Color
        fields = ('name', 'hex_code', 'is_active')


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('name', 'slug', 'category', 'description', 'price', 'image', 'is_active', 'featured')


class ProductVariantForm(forms.ModelForm):
    # Stock changes use inventory.services.adjust_stock, keeping an audit trail.
    class Meta:
        model = ProductVariant
        fields = ('product', 'size', 'color', 'sku', 'is_active')
