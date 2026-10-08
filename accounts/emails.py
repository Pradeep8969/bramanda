import logging
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from .models import User

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
    user_id = user.pk

    def send():
        message = EmailMultiAlternatives(
            WELCOME_SUBJECT, render_to_string('accounts/email/welcome.txt', context),
            settings.DEFAULT_FROM_EMAIL, [recipient],
        )
        message.attach_alternative(render_to_string('accounts/email/welcome.html', context), 'text/html')
        try:
            message.send()
        except (SMTPException, OSError):
            # Signup remains successful. No credentials, password, or recipient in logs.
            logger.error('Welcome email delivery failed for user id %s.', user_id)

    transaction.on_commit(send)
