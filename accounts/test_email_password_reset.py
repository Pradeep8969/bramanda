import re
from datetime import datetime, timedelta
from smtplib import SMTPException
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from . import test_social_auth as social_helpers
from .emails import WELCOME_SUBJECT, schedule_welcome_email

User = get_user_model()
PASSWORD = 'Bramanda-Local-Password-845!'
NEW_PASSWORD = 'Bramanda-New-Password-2026!'
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


@override_settings(MAILERS=LOCAL_MAILERS, PUBLIC_BASE_URL='https://bramanda.example')
class SocialPasswordCreationTests(TestCase):
    provider_data = SocialWelcomeTests.provider_data
    oauth_login = SocialWelcomeTests.oauth_login
    setUp = SocialWelcomeTests.setUp

    def check_password_creation(self, provider):
        from allauth.socialaccount.models import SocialAccount
        self.assertRedirects(self.oauth_login(provider), '/shop/')
        account = SocialAccount.objects.get(provider=provider)
        user = account.user
        self.assertFalse(user.has_usable_password())
        original_password = user.password
        self.client.logout()
        mail.outbox.clear()
        self.assertRedirects(self.client.post('/forgot-password/', {'email': user.email.upper()}),
                             '/password-reset/done/')
        self.assertEqual(len(mail.outbox), 1)
        user.refresh_from_db()
        self.assertEqual(user.password, original_password)
        path = urlsplit(re.search(r'https://bramanda\.example/reset/[^\s]+', mail.outbox[0].body).group()).path
        self.assertTrue(default_token_generator.check_token(user, path.rstrip('/').split('/')[-1]))
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        invalid = self.client.post(reverse('accounts:password_reset_confirm', args=[uid, 'invalid-token']),
                                   {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertFalse(invalid.context['validlink'])
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())
        page = self.client.get(path, follow=True)
        self.assertTrue(page.context['validlink'])
        self.assertRedirects(self.client.post(page.wsgi_request.path, {
            'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}), '/reset/done/')
        user.refresh_from_db()
        self.assertTrue(user.has_usable_password())
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertRedirects(self.client.post('/login/', {'username': user.username, 'password': NEW_PASSWORD}), '/shop/')
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        self.client.logout()
        self.assertFalse(self.client.get(path).context['validlink'])
        self.assertRedirects(self.oauth_login(provider), '/shop/')
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        account.refresh_from_db()
        self.assertEqual(account.user_id, user.pk)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 1)
        user.refresh_from_db()
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.get('/staff/').status_code, 403)
        self.assertEqual(self.client.get('/owner/').status_code, 403)

    def test_google_customer_creates_password_and_keeps_social_login(self):
        self.check_password_creation('google')

    def test_facebook_customer_creates_password_and_keeps_social_login(self):
        self.check_password_creation('facebook')


@override_settings(MAILERS=LOCAL_MAILERS, PUBLIC_BASE_URL='https://bramanda.example')
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='customer', email='customer@example.com', password=PASSWORD)

    def reset_path(self):
        self.client.post('/forgot-password/', {'email': self.user.email})
        url = re.search(r'https://bramanda\.example/reset/[^\s]+', mail.outbox[-1].body).group()
        return urlsplit(url).path

    def test_forgot_password_page_and_login_link(self):
        self.assertContains(self.client.get('/forgot-password/'), 'Forgot password?')
        self.assertContains(self.client.get('/login/'), 'href="/forgot-password/"')

    def test_known_email_sends_valid_branded_reset_url(self):
        path = self.reset_path()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Reset your BRAMANDA password')
        self.assertIn('THE UNDISCOVERED', message.body)
        self.assertEqual(message.alternatives[0].mimetype, 'text/html')
        self.assertNotIn(PASSWORD, message.body + message.alternatives[0].content)
        token = path.rstrip('/').split('/')[-1]
        self.assertTrue(default_token_generator.check_token(self.user, token))

    def test_known_and_unknown_email_show_identical_generic_confirmation(self):
        known = self.client.post('/forgot-password/', {'email': self.user.email}, follow=True)
        mail.outbox.clear()
        unknown = self.client.post('/forgot-password/', {'email': 'unknown@example.com'}, follow=True)
        self.assertEqual(known.content, unknown.content)
        self.assertContains(unknown, "If an eligible BRAMANDA account exists for that email address")
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_email_lookup_case_insensitive(self):
        self.client.post('/forgot-password/', {'email': 'CUSTOMER@EXAMPLE.COM'})
        self.assertEqual(len(mail.outbox), 1)

    def test_valid_token_changes_password_old_login_fails_new_login_works(self):
        original_path = self.reset_path()
        form_page = self.client.get(original_path, follow=True)
        self.assertTrue(form_page.context['validlink'])
        # Django replaces the token in the URL with set-password before showing the form.
        form_path = form_page.wsgi_request.path
        response = self.client.post(form_path, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertRedirects(response, '/reset/done/')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.post('/login/', {'username': self.user.username, 'password': PASSWORD})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.post('/login/', {'username': self.user.username, 'password': NEW_PASSWORD}), '/shop/')
        self.assertEqual(self.client.get('/staff/').status_code, 403)
        self.assertEqual(self.client.get('/owner/').status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'CUSTOMER')
        self.client.logout()
        self.assertFalse(self.client.get(original_path).context['validlink'])

    def test_invalid_token_cannot_change_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        path = reverse('accounts:password_reset_confirm', args=[uid, 'invalid-token'])
        response = self.client.post(path, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertFalse(response.context['validlink'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_expired_token_cannot_change_password(self):
        with patch.object(default_token_generator, '_now', return_value=datetime.now() - timedelta(hours=2)):
            token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(reverse('accounts:password_reset_confirm', args=[uid, token]))
        self.assertFalse(response.context['validlink'])

    def test_password_validators_and_confirmation_remain_enabled(self):
        page = self.client.get(self.reset_path(), follow=True)
        response = self.client.post(page.wsgi_request.path, {'new_password1': '123', 'new_password2': '123'})
        self.assertTrue(response.context['form'].errors)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_customer_without_local_password_or_social_account_can_create_password(self):
        self.user.set_unusable_password()
        self.user.save()
        page = self.client.get(self.reset_path(), follow=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(page.context['validlink'])
        self.assertRedirects(self.client.post(page.wsgi_request.path, {
            'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}), '/reset/done/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_usable_password())
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_ineligible_users_show_same_confirmation_and_receive_no_email(self):
        expected = self.client.post('/forgot-password/', {'email': self.user.email}, follow=True)
        mail.outbox.clear()
        self.user.is_active = False
        self.user.save()
        emails = [self.user.email, 'unknown@example.com']
        for role in ('OWNER', 'STAFF'):
            user = User.objects.create_user(username=role.lower(), role=role,
                                            email=role.lower() + '@example.com', password=PASSWORD)
            emails.append(user.email)
        for email in emails:
            with self.subTest(email=email):
                response = self.client.post('/forgot-password/', {'email': email}, follow=True)
                self.assertEqual(response.content, expected.content)
                self.assertEqual(response.redirect_chain, expected.redirect_chain)
                self.assertEqual(len(mail.outbox), 0)

    def test_customer_without_email_is_not_eligible(self):
        from .forms import CustomerPasswordResetForm
        self.user.email = ''
        self.user.save()
        self.assertEqual(list(CustomerPasswordResetForm().get_users('')), [])

    def test_owner_staff_excluded_from_customer_reset(self):
        for role in ('OWNER', 'STAFF'):
            user = User.objects.create_user(username=role.lower(), role=role, email=role.lower() + '@example.com', password=PASSWORD)
            self.assertRedirects(self.client.post('/forgot-password/', {'email': user.email}), '/password-reset/done/')
            user.refresh_from_db()
            self.assertEqual(user.role, role)
            self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(len(mail.outbox), 0)

    def test_request_and_confirm_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/forgot-password/', {'email': self.user.email}).status_code, 403)
        page = client.get(self.reset_path(), follow=True)
        self.assertEqual(client.post(page.wsgi_request.path, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}).status_code, 403)
        token = client.cookies['csrftoken'].value
        response = client.post(page.wsgi_request.path, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD,
                                                      'csrfmiddlewaretoken': token})
        self.assertRedirects(response, '/reset/done/')

    def test_email_origin_does_not_trust_incoming_host(self):
        with override_settings(ALLOWED_HOSTS=['untrusted.example']):
            self.client.post('/forgot-password/', {'email': self.user.email}, HTTP_HOST='untrusted.example')
        self.assertIn('https://bramanda.example/reset/', mail.outbox[0].body)
        self.assertNotIn('untrusted.example', mail.outbox[0].body)
