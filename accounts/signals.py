from allauth.account.signals import user_signed_up
from django.dispatch import receiver

from .emails import schedule_welcome_email


@receiver(user_signed_up, dispatch_uid='bramanda.customer_welcome_on_allauth_signup')
def welcome_allauth_customer(sender, user, **kwargs):
    # Emitted on signup only, not returning login or account connection.
    schedule_welcome_email(user)
