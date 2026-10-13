from uuid import uuid4

from django import forms

from orders.models import Order
from products.models import ProductVariant


class OrderStatusForm(forms.Form):
    order_status = forms.ChoiceField(
        choices=[
            (value, label)
            for value, label in Order.OrderStatus.choices
            if value != Order.OrderStatus.CANCELLED
        ]
    )


class DeliveryStatusForm(forms.Form):
    delivery_status = forms.ChoiceField(choices=Order.DeliveryStatus.choices)


class CODPaymentForm(forms.Form):
    payment_status = forms.ChoiceField(
        choices=[
            (Order.PaymentStatus.PAID, "Paid"),
            (Order.PaymentStatus.UNPAID, "Payment Remaining"),
        ]
    )


class StockAdjustmentForm(forms.Form):
    adjustment_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True)
    )
    quantity_change = forms.IntegerField(min_value=-2147483647, max_value=2147483647)
    note = forms.CharField(
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Note / reason",
    )

    def clean_quantity_change(self):
        value = self.cleaned_data["quantity_change"]
        if value == 0:
            raise forms.ValidationError("Enter a nonzero quantity change.")
        return value


class StockUpdateForm(forms.Form):
    variant = forms.ModelChoiceField(
        queryset=ProductVariant.objects.filter(is_active=True)
    )
    quantity = forms.IntegerField(min_value=0, max_value=2147483647)
    expected_stock = forms.IntegerField(min_value=0, max_value=2147483647)
    expected_updated_at = forms.CharField(max_length=64)

    def clean(self):
        data = super().clean()
        # IntegerField accepts "12.0"; require whole-number syntax at this endpoint.
        for name in ("quantity", "expected_stock"):
            if (
                not self.data.get(name, "").isascii()
                or not self.data.get(name, "").isdigit()
            ):
                self.add_error(name, "Enter a non-negative whole number.")
        return data
