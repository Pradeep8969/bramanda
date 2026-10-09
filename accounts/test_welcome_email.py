from smtplib import SMTPAuthenticationError, SMTPException
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings

from . import test_social_auth as social_helpers
from .emails import WELCOME_SUBJECT, schedule_welcome_email

User = get_user_model()
PASSWORD = 'Bramanda-Local-Password-845!'
LOCAL_MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}}


@override_settings(MAILERS=LOCAL_MAILERS, PUBLIC_BASE_URL='https://bramanda.example')
class WelcomeEmailTests(TestCase):
    def register(self, **changes):
        data = {'username': 'newcustomer', 'email': 'new@example.com', 'first_name': 'Asha',
                'password1': PASSWORD, 'password2': PASSWORD}
        data.update(changes)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post('/register/', data)

    def test_registration_requires_email(self):
        response = self.register(email='')
        self.assertIn('email', response.context['form'].errors)
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_trims_normalizes_email(self):
        self.assertRedirects(self.register(email='  NEW@Example.COM  '), '/shop/')
        self.assertEqual(User.objects.get().email, 'new@example.com')

    def test_duplicate_local_email_is_rejected_case_insensitively(self):
        for role in ('CUSTOMER', 'STAFF', 'OWNER'):
            with self.subTest(role=role):
                User.objects.all().delete()
                user = User.objects.create_user(username='existing', email='Taken@Example.com', role=role)
                original_email = user.email
                response = self.register(email=' taken@EXAMPLE.com ')
                self.assertIn('email', response.context['form'].errors)
                self.assertEqual(User.objects.count(), 1)
                user.refresh_from_db()
                self.assertEqual(user.email, original_email)
                self.assertEqual(user.role, role)
        self.assertEqual(len(mail.outbox), 0)

    def test_normal_registration_sends_one_branded_multipart_welcome(self):
        self.assertRedirects(self.register(), '/shop/')
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, WELCOME_SUBJECT)
        self.assertEqual(message.to, ['new@example.com'])
        self.assertIn('Asha', message.body)
        self.assertIn('THE UNDISCOVERED', message.body)
        self.assertIn('https://bramanda.example/shop/', message.body)
        self.assertIn('https://bramanda.example/login/', message.body)
        self.assertEqual(message.alternatives[0].mimetype, 'text/html')
        self.assertNotIn(PASSWORD, message.body + message.alternatives[0].content)
        self.assertNotIn(User.objects.get().password, message.body)

    def test_welcome_uses_username_when_first_name_missing(self):
        self.register(first_name='')
        self.assertIn('Welcome, newcustomer!', mail.outbox[0].body)

    def test_password_login_does_not_send_another_welcome(self):
        self.register()
        self.client.logout()
        self.client.post('/login/', {'username': 'newcustomer', 'password': PASSWORD})
        self.assertEqual(len(mail.outbox), 1)

    def test_owner_staff_login_does_not_send_customer_welcome(self):
        for role in ('OWNER', 'STAFF'):
            self.client.logout()
            user = User.objects.create_user(username=role.lower(), password=PASSWORD, role=role,
                                            email=role.lower() + '@example.com')
            self.client.post('/login/', {'username': user.username, 'password': PASSWORD})
            self.assertEqual(self.client.get('/staff/').status_code, 200)
            self.assertEqual(self.client.get('/owner/').status_code, 200 if role == 'OWNER' else 403)
            with self.captureOnCommitCallbacks(execute=True):
                schedule_welcome_email(user)
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_does_not_break_registration(self):
        with patch('accounts.emails.EmailMultiAlternatives.send', side_effect=SMTPException('failed')), \
                self.assertLogs('accounts.emails', level='ERROR'):
            self.assertRedirects(self.register(), '/shop/')
        self.assertEqual(User.objects.count(), 1)

    def test_zero_result_and_auth_errors_are_sanitized(self):
        user = User.objects.create_user(username='welcome', email='welcome@example.com')
        for result in (0, SMTPAuthenticationError(535, b'secret-token')):
            kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with patch('accounts.emails.EmailMultiAlternatives.send', **kwargs), \
                    self.assertLogs('accounts.emails', 'ERROR') as logs, \
                    self.captureOnCommitCallbacks(execute=True):
                schedule_welcome_email(user)
            self.assertNotIn('secret-token', ''.join(logs.output))
            self.assertNotIn(user.email, ''.join(logs.output))

    def test_rolled_back_creation_does_not_send_welcome(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    user = User.objects.create_user(username='rollback', email='rollback@example.com')
                    schedule_welcome_email(user)
                    raise ValueError('rollback')
            except ValueError:
                pass
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)


@override_settings(MAILERS=LOCAL_MAILERS)
class SocialWelcomeTests(TestCase):
    provider_data = social_helpers.SocialAuthTests.provider_data
    oauth_login = social_helpers.SocialAuthTests.oauth_login

    def setUp(self):
        from allauth.socialaccount.models import SocialApp
        for provider in ('google', 'facebook'):
            SocialApp.objects.create(provider=provider, name=provider.title(),
                                     client_id='test-client', secret='test-only-secret')
        network = patch('requests.sessions.Session.request', side_effect=AssertionError('No external OAuth'))
        network.start()
        self.addCleanup(network.stop)

    def welcome_messages(self):
        # allauth may also send its own optional email-verification message.
        return [message for message in mail.outbox if message.subject == WELCOME_SUBJECT]

    def test_google_signup_sends_one_welcome_returning_login_sends_none(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.oauth_login()
        self.assertEqual(len(self.welcome_messages()), 1)
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            self.oauth_login()
        self.assertEqual(len(self.welcome_messages()), 1)

    def test_facebook_signup_sends_one_welcome_returning_login_sends_none(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.oauth_login('facebook')
        self.assertEqual(len(self.welcome_messages()), 1)
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            self.oauth_login('facebook')
        self.assertEqual(len(self.welcome_messages()), 1)

    def test_social_signup_without_email_does_not_send_welcome_or_create_password(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.oauth_login('facebook', email=None), '/shop/')
        self.assertEqual(len(self.welcome_messages()), 0)
        self.assertFalse(User.objects.get().has_usable_password())
