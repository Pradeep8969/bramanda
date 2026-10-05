from django import forms
from orders.models import Order
from products.models import ProductVariant


class OrderStatusForm(forms.Form):
    order_status = forms.ChoiceField(choices=Order.OrderStatus.choices)


class DeliveryStatusForm(forms.Form):
    delivery_status = forms.ChoiceField(choices=Order.DeliveryStatus.choices)


class CODPaymentForm(forms.Form):
    payment_status = forms.ChoiceField(choices=[(Order.PaymentStatus.PAID, 'Paid')])


class StockAdjustmentForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=ProductVariant.objects.filter(is_active=True))
    quantity_change = forms.IntegerField(min_value=-2147483647, max_value=2147483647)
    note = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={'rows': 2}), label='Note / reason')

    def clean_quantity_change(self):
        value = self.cleaned_data['quantity_change']
        if value == 0:
            raise forms.ValidationError('Enter a nonzero quantity change.')
        return value
