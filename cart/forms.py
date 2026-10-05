from django import forms

from products.models import ProductVariant


def available_variants():
    return ProductVariant.objects.filter(
        is_active=True, product__is_active=True, product__category__is_active=True,
        color__is_active=True, size__is_active=True, stock_quantity__gt=0,
    ).select_related('product', 'product__category', 'size', 'color')


class QuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=1, max_value=2147483647, initial=1)


class VariantChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, variant):
        return f'{variant.color.name} / {variant.size.name} — {variant.stock_quantity} available'


class AddToCartForm(QuantityForm):
    variant = VariantChoiceField(queryset=ProductVariant.objects.none(), empty_label='Select color / size')

    def __init__(self, *args, product, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variant'].queryset = available_variants().filter(product=product)

    def clean(self):
        cleaned = super().clean()
        variant, quantity = cleaned.get('variant'), cleaned.get('quantity')
        if variant and quantity and quantity > variant.stock_quantity:
            self.add_error('quantity', f'Only {variant.stock_quantity} are currently available.')
        return cleaned

