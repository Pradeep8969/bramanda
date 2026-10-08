from django import forms
from django.core.validators import RegexValidator
from .models import Order


class CheckoutForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    phone_number = forms.CharField(max_length=30, validators=[
        RegexValidator(r'^\+?[0-9 ()-]{7,30}$', 'Enter a valid phone number, including an area code if needed.'),
    ])
    shipping_address = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={'rows': 4}))
    payment_method = forms.ChoiceField(choices=Order.PaymentMethod.choices, initial=Order.PaymentMethod.COD,
                                     widget=forms.RadioSelect)

