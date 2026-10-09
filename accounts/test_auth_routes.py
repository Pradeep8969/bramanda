from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, Resolver404, get_resolver, resolve, reverse


@override_settings(MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}})
class AuthenticationRouteTests(TestCase):
    def test_recovery_urls_are_unavailable_for_get_and_post(self):
        paths = (
            '/forgot-password/', '/password-reset/done/', '/reset/MQ/example-token/', '/reset/done/',
            '/accounts/password/reset/', '/accounts/password/reset/done/',
            '/accounts/password/reset/key/done/', '/accounts/password/reset/key/1-example-token/',
            '/accounts/password/reset/confirm/', '/accounts/password/reset/complete/',
        )
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)
                self.assertEqual(self.client.get(path).status_code, 404)
                self.assertEqual(self.client.post(path, {'email': 'customer@example.com'}).status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    def test_recovery_route_names_are_not_registered(self):
        for name in ('accounts:password_reset', 'accounts:password_reset_done',
                     'accounts:password_reset_confirm', 'accounts:password_reset_complete',
                     'account_reset_password', 'account_reset_password_done',
                     'account_reset_password_from_key', 'account_reset_password_from_key_done',
                     'account_confirm_password_reset_code', 'account_complete_password_reset',
                     'account_password_reset_completed'):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)

        def names(patterns):
            for pattern in patterns:
                if hasattr(pattern, 'url_patterns'):
                    yield from names(pattern.url_patterns)
                elif pattern.name:
                    yield pattern.name

        self.assertFalse(any('reset_password' in name or 'password_reset' in name
                             for name in names(get_resolver().url_patterns)))

    def test_login_and_signup_pages_render_without_recovery_links(self):
        for name in ('accounts:login', 'accounts:register', 'account_login', 'account_signup'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Forgot password')
                self.assertNotContains(response, 'Forgot your password')
                self.assertNotContains(response, '/password/reset/')
                self.assertNotContains(response, '/forgot-password/')

    def test_signup_login_logout_and_profile_remain_available(self):
        password = 'Local-Customer-Password-845!'
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/register/', {
                'username': 'customer', 'email': 'customer@example.com',
                'password1': password, 'password2': password,
            })
        self.assertRedirects(response, '/shop/')
        user = get_user_model().objects.get(username='customer')
        self.assertTrue(user.check_password(password))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.client.get('/profile/').status_code, 200)
        self.assertRedirects(self.client.post('/logout/'), '/')
        self.assertRedirects(self.client.post('/login/', {'username': 'customer', 'password': password}), '/shop/')
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))

    def test_allauth_password_change_set_and_social_routes_remain(self):
        for name in ('account_change_password', 'account_set_password',
                     'google_login', 'google_callback', 'facebook_login', 'facebook_callback',
                     'socialaccount_connections'):
            with self.subTest(name=name):
                self.assertEqual(resolve(reverse(name)).url_name, name)
        user = get_user_model().objects.create_user(username='customer', password='local-password')
        self.client.force_login(user)
        response = self.client.get(reverse('account_change_password'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '/password/reset/')
