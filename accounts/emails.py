import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from .models import User
from .mail_diagnostics import send_safely

logger = logging.getLogger(__name__)
WELCOME_SUBJECT = 'Welcome to BRAMANDA – THE UNDISCOVERED'


def schedule_welcome_email(user):
    """Call once on signup, never login; do not deliver for rolled-back signups."""
    if user.role != User.Role.CUSTOMER or not user.email:
        return
    context = {
        'customer_name': user.first_name or user.username,
        'login_url': settings.PUBLIC_BASE_URL + reverse('accounts:login'),
        'shop_url': settings.PUBLIC_BASE_URL + reverse('products:shop'),
    }
    recipient = user.email

    def send():
        message = EmailMultiAlternatives(
            WELCOME_SUBJECT, render_to_string('accounts/email/welcome.txt', context),
            settings.DEFAULT_FROM_EMAIL, [recipient],
        )
        message.attach_alternative(render_to_string('accounts/email/welcome.html', context), 'text/html')
        send_safely(message, logger, 'Welcome')

    transaction.on_commit(send)
