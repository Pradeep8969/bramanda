from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from allauth import app_settings as allauth_settings
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.admin import SocialAppForm
from allauth.socialaccount.models import SocialAccount, SocialApp
from allauth.socialaccount.providers.facebook.views import FacebookOAuth2Adapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()
PASSWORD = 'Bramanda-Social-Test-845!'


class SocialAuthTests(TestCase):
    def setUp(self):
        # Test-only dummy credentials live only in the isolated test database.
        for provider in ('google', 'facebook'):
            SocialApp.objects.create(provider=provider, name=provider.title(),
                                     client_id='test-client', secret='test-only-not-a-real-secret')
        # A missed mock must fail, rather than contact either provider.
        network = patch('requests.sessions.Session.request',
                        side_effect=AssertionError('OAuth tests must not use the network'))
        network.start()
        self.addCleanup(network.stop)

    def provider_data(self, provider, uid='social-123', email='social@example.com'):
        if provider == 'google':
            return {'sub': uid, 'email': email, 'email_verified': True,
                    'given_name': 'Asha', 'family_name': 'Rai'}
        return {'id': uid, 'email': email, 'first_name': 'Asha', 'last_name': 'Rai'}

    def oauth_login(self, provider='google', uid='social-123', email='social@example.com',
                    next_url=None, malicious_role=None):
        data = self.provider_data(provider, uid, email)
        adapter_class = GoogleOAuth2Adapter if provider == 'google' else FacebookOAuth2Adapter

        def complete_login(adapter, request, app, token, **kwargs):
            sociallogin = adapter.get_provider().sociallogin_from_response(request, data)
            if malicious_role:
                sociallogin.user.role = malicious_role
                sociallogin.user.is_staff = True
                sociallogin.user.is_superuser = True
            return sociallogin

        params = {'next': next_url} if next_url else {}
        start = self.client.post(reverse(provider + '_login'), params)
        self.assertEqual(start.status_code, 302)
        query = parse_qs(urlsplit(start.url).query)
        self.assertEqual(query['redirect_uri'], ['http://testserver' + reverse(provider + '_callback')])
        with patch('allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token',
                   return_value={'access_token': 'test-access-token'}), \
                patch.object(adapter_class, 'complete_login', autospec=True, side_effect=complete_login):
            return self.client.get(reverse(provider + '_callback'),
                                   {'code': 'test-code', 'state': query['state'][0]})

    def test_custom_user_and_secure_settings(self):
        self.assertEqual(settings.AUTH_USER_MODEL, 'accounts.User')
        self.assertFalse(settings.SOCIALACCOUNT_LOGIN_ON_GET)
        self.assertFalse(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION)
        self.assertFalse(settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT)
        self.assertNotIn('APP', settings.SOCIALACCOUNT_PROVIDERS['google'])
        self.assertNotIn('APPS', settings.SOCIALACCOUNT_PROVIDERS['facebook'])

    def test_socialapp_configuration_does_not_require_sites(self):
        self.assertFalse(allauth_settings.SITES_ENABLED)
        self.assertNotIn('sites', SocialAppForm().fields)
        request = self.client.get('/login/').wsgi_request
        for provider in ('google', 'facebook'):
            self.assertEqual(get_adapter().get_provider(request, provider).app.provider, provider)

    def test_socialapp_admin_form_accepts_provider_credentials(self):
        SocialApp.objects.all().delete()
        for provider in ('google', 'facebook'):
            form = SocialAppForm(data={'provider': provider, 'provider_id': '',
                                      'name': provider.title(), 'client_id': 'test-id',
                                      'secret': 'test-secret', 'key': '', 'settings': '{}'})
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        self.assertContains(self.client.get('/login/'), 'Continue with Google')
        self.assertContains(self.client.get('/login/'), 'Continue with Facebook')

    def test_normal_customer_login(self):
        user = User.objects.create_user(username='passwordcustomer', password=PASSWORD)
        response = self.client.post('/login/', {'username': user.username, 'password': PASSWORD})
        self.assertRedirects(response, '/shop/')
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        self.assertEqual(self.client.session['_auth_user_backend'],
                         'django.contrib.auth.backends.ModelBackend')

    def test_normal_registration(self):
        response = self.client.post('/register/', {
            'username': 'registered', 'email': 'registered@example.com',
            'password1': PASSWORD, 'password2': PASSWORD, 'role': 'OWNER',
        })
        self.assertRedirects(response, '/shop/')
        user = User.objects.get(username='registered')
        self.assertEqual(user.role, 'CUSTOMER')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_login_page_renders_google_post_form(self):
        response = self.client.get('/login/')
        self.assertContains(response, 'Continue with Google')
        self.assertContains(response, 'method="post" action="/accounts/google/login/?process=login"')
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_login_page_renders_facebook_post_form(self):
        response = self.client.get('/login/')
        self.assertContains(response, 'Continue with Facebook')
        self.assertContains(response, 'method="post" action="/accounts/facebook/login/?process=login"')

    def test_register_page_renders_both_providers(self):
        response = self.client.get('/register/')
        for provider in ('Google', 'Facebook'):
            self.assertContains(response, 'Continue with ' + provider)
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')

    def test_pages_without_credentials_keep_password_forms(self):
        SocialApp.objects.all().delete()
        for url in ('/login/', '/register/'):
            response = self.client.get(url)
            self.assertContains(response, 'Continue with Google')
            self.assertContains(response, 'Continue with Facebook')
            self.assertContains(response, 'disabled', count=2)
            self.assertContains(response, 'Social sign in is currently unavailable')
            self.assertContains(response, 'name="username"')
        self.test_normal_registration()
        self.client.logout()
        self.test_normal_customer_login()

    def test_single_configured_provider_does_not_crash(self):
        SocialApp.objects.filter(provider='facebook').delete()
        response = self.client.get('/login/')
        self.assertContains(response, 'Continue with Google')
        self.assertNotContains(response, '/accounts/facebook/login/')

    def test_get_does_not_initiate_oauth(self):
        for provider in ('google', 'facebook'):
            response = self.client.get(reverse(provider + '_login'))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('socialaccount_states', self.client.session)
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_provider_initiation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for provider in ('google', 'facebook'):
            self.assertEqual(client.post(reverse(provider + '_login')).status_code, 403)
        client.get('/login/')
        token = client.cookies['csrftoken'].value
        for provider in ('google', 'facebook'):
            response = client.post(reverse(provider + '_login'), {'csrfmiddlewaretoken': token})
            self.assertEqual(response.status_code, 302)
            query = parse_qs(urlsplit(response.url).query)
            expected = {'profile', 'email'} if provider == 'google' else {'public_profile', 'email'}
            self.assertEqual(set(query['scope'][0].replace(',', ' ').split()), expected)

    def test_google_auto_signup_preserves_details_and_has_no_password(self):
        response = self.oauth_login()
        self.assertRedirects(response, '/shop/')
        user = SocialAccount.objects.get(provider='google').user
        self.assertEqual((user.first_name, user.last_name, user.email), ('Asha', 'Rai', 'social@example.com'))
        self.assertEqual(user.role, 'CUSTOMER')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_facebook_auto_signup(self):
        self.assertRedirects(self.oauth_login('facebook'), '/shop/')
        user = SocialAccount.objects.get(provider='facebook').user
        self.assertEqual(user.role, 'CUSTOMER')
        self.assertEqual((user.first_name, user.last_name, user.email), ('Asha', 'Rai', 'social@example.com'))
        self.assertFalse(user.has_usable_password())

    def test_signup_adapter_cannot_grant_privileges(self):
        for role in ('OWNER', 'STAFF'):
            with self.subTest(role=role):
                self.client.logout()
                response = self.oauth_login(uid=role, email=role.lower() + '@example.com', malicious_role=role)
                self.assertRedirects(response, '/shop/')
                user = SocialAccount.objects.get(uid=role).user
                self.assertEqual(user.role, 'CUSTOMER')
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)

    def test_returning_social_user_logs_in_without_duplicate(self):
        self.oauth_login()
        user_id = SocialAccount.objects.get().user_id
        self.client.logout()
        self.assertRedirects(self.oauth_login(), '/shop/')
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.count(), 1)
        self.assertEqual(self.client.session['_auth_user_id'], str(user_id))

    def test_social_customer_denied_staff_and_owner(self):
        self.oauth_login()
        self.assertEqual(self.client.get('/staff/').status_code, 403)
        self.assertEqual(self.client.get('/owner/').status_code, 403)

    def test_existing_owner_and_staff_password_permissions_unchanged(self):
        for role in ('OWNER', 'STAFF'):
            self.client.logout()
            user = User.objects.create_user(username=role.lower(), role=role, password=PASSWORD)
            self.client.post('/login/', {'username': user.username, 'password': PASSWORD})
            self.assertEqual(self.client.get('/staff/').status_code, 200)
            self.assertEqual(self.client.get('/owner/').status_code, 200 if role == 'OWNER' else 403)
            user.refresh_from_db()
            self.assertEqual(user.role, role)

    def test_returning_social_login_does_not_overwrite_existing_roles_or_passwords(self):
        for role in ('OWNER', 'STAFF'):
            self.client.logout()
            user = User.objects.create_user(username=role.lower(), role=role, password=PASSWORD,
                                            email=role.lower() + '@example.com')
            SocialAccount.objects.create(user=user, provider='google', uid=role)
            self.assertRedirects(self.oauth_login(uid=role, email=user.email), '/shop/')
            user.refresh_from_db()
            self.assertEqual(user.role, role)
            self.assertTrue(user.check_password(PASSWORD))

    def test_duplicate_email_never_authenticates_or_merges_existing_account(self):
        for provider in ('google', 'facebook'):
            for role in ('CUSTOMER', 'OWNER', 'STAFF'):
                with self.subTest(provider=provider, role=role):
                    self.client.logout()
                    email = provider + role.lower() + '@example.com'
                    user = User.objects.create_user(username=provider + role, role=role,
                                                    email=email, password=PASSWORD)
                    response = self.oauth_login(provider, uid=provider + role, email=email.upper())
                    self.assertRedirects(response, reverse('socialaccount_signup'))
                    self.assertNotIn('_auth_user_id', self.client.session)
                    self.assertFalse(SocialAccount.objects.filter(uid=provider + role).exists())
                    form_page = self.client.get(response.url)
                    self.assertNotContains(form_page, 'name="password1"')
                    retry = self.client.post(response.url, {'username': 'new' + provider + role, 'email': email})
                    self.assertContains(retry, 'An account already exists with this email address')
                    self.assertFalse(User.objects.filter(username='new' + provider + role).exists())
                    user.refresh_from_db()
                    self.assertEqual(user.role, role)
                    self.assertTrue(user.check_password(PASSWORD))

    def test_customer_can_connect_social_account_after_password_login(self):
        user = User.objects.create_user(username='existing', email='social@example.com', password=PASSWORD)
        self.client.login(username=user.username, password=PASSWORD)
        start = self.client.post(reverse('google_login'), {'process': 'connect'})
        state = parse_qs(urlsplit(start.url).query)['state'][0]

        def complete_login(adapter, request, app, token, **kwargs):
            return adapter.get_provider().sociallogin_from_response(request, self.provider_data('google'))

        with patch('allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token',
                   return_value={'access_token': 'test-token'}), \
                patch.object(GoogleOAuth2Adapter, 'complete_login', autospec=True, side_effect=complete_login):
            response = self.client.get(reverse('google_callback'), {'code': 'test-code', 'state': state})
        self.assertRedirects(response, reverse('socialaccount_connections'))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(SocialAccount.objects.get().user_id, user.pk)
        user.refresh_from_db()
        self.assertEqual(user.role, 'CUSTOMER')
        self.assertTrue(user.check_password(PASSWORD))

    def test_safe_customer_next_is_preserved(self):
        self.assertRedirects(self.oauth_login(next_url='/cart/'), '/cart/')

    def test_unsafe_or_management_next_falls_back_to_shop(self):
        for index, next_url in enumerate(('/owner/', '/staff/', '/admin/', '/%6fwner/',
                                          'https://evil.example/shop/', '//evil.example/shop/')):
            with self.subTest(next_url=next_url):
                self.client.logout()
                response = self.oauth_login(uid=str(index), email=f'next{index}@example.com', next_url=next_url)
                self.assertRedirects(response, '/shop/')

    def test_anonymous_protected_pages_still_redirect_to_normal_login(self):
        for url in ('/profile/', '/cart/', '/orders/', '/staff/', '/owner/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, '/login/?next=' + url)

    def test_invalid_callback_state_does_not_authenticate(self):
        for provider in ('google', 'facebook'):
            response = self.client.get(reverse(provider + '_callback'), {'code': 'test', 'state': 'forged'})
            self.assertEqual(response.status_code, 401)
            self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(User.objects.exists())
