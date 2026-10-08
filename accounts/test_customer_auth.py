from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()


class CustomerAuthTests(TestCase):
    def registration_data(self, **changes):
        data = {'username': 'newcustomer', 'first_name': 'Asha', 'last_name': 'Rai',
                'email': 'asha@example.com', 'phone_number': '9800000001', 'address': 'Kathmandu',
                'password1': 'Strong-Test-Password-845!', 'password2': 'Strong-Test-Password-845!'}
        data.update(changes)
        return data

    def test_registration_page(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('role', response.context['form'].fields)

    def test_registration_creates_customer_hashes_password_and_logs_in(self):
        response = self.client.post(reverse('accounts:register'), self.registration_data(), follow=True)
        user = User.objects.get(username='newcustomer')
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertTrue(user.check_password('Strong-Test-Password-845!'))
        self.assertNotEqual(user.password, 'Strong-Test-Password-845!')
        self.assertEqual(user.phone_number, '9800000001')
        self.assertEqual(str(user.pk), self.client.session['_auth_user_id'])
        self.assertContains(response, 'Your customer account is ready')

    def test_public_registration_cannot_assign_privileged_roles(self):
        for role in ('OWNER', 'STAFF'):
            with self.subTest(role=role):
                self.client.logout()
                self.client.post(reverse('accounts:register'), self.registration_data(username=role.lower(), email=role.lower() + '@example.com', role=role, is_staff='true', is_superuser='true'))
                user = User.objects.get(username=role.lower())
                self.assertEqual(user.role, User.Role.CUSTOMER)
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(reverse('accounts:register'), self.registration_data(password2='Different-password!'))
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(User.objects.exists())

    def test_registration_rejects_duplicate_username(self):
        User.objects.create_user(username='newcustomer')
        response = self.client.post(reverse('accounts:register'), self.registration_data())
        self.assertIn('username', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_registration_runs_password_validation(self):
        response = self.client.post(reverse('accounts:register'), self.registration_data(password1='123', password2='123'))
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(User.objects.exists())

    def make_user(self):
        return User.objects.create_user(username='customer', password='Strong-Test-Password-845!')

    def test_login_and_safe_next(self):
        user = self.make_user()
        response = self.client.post('/login/?next=/profile/', {'username': user.username, 'password': 'Strong-Test-Password-845!'})
        self.assertRedirects(response, '/profile/')
        self.assertEqual(str(user.pk), self.client.session['_auth_user_id'])

    def test_external_next_is_rejected(self):
        self.make_user()
        response = self.client.post('/login/?next=https://evil.example/', {'username': 'customer', 'password': 'Strong-Test-Password-845!', 'next': 'https://evil.example/'})
        self.assertRedirects(response, '/shop/')

    def test_invalid_login_shows_error(self):
        self.make_user()
        response = self.client.post('/login/', {'username': 'customer', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_user_cannot_login(self):
        user = self.make_user()
        user.is_active = False
        user.save()
        self.client.post('/login/', {'username': 'customer', 'password': 'Strong-Test-Password-845!'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logged_in_users_skip_login_and_registration(self):
        self.client.force_login(self.make_user())
        self.assertRedirects(self.client.get('/login/'), '/shop/')
        self.assertRedirects(self.client.get('/register/'), '/profile/')

    def test_logout_is_post_only(self):
        self.client.force_login(self.make_user())
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        response = self.client.post('/logout/')
        self.assertRedirects(response, '/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_profile_requires_login(self):
        self.assertRedirects(self.client.get('/profile/'), '/login/?next=/profile/')

    def test_profile_edits_only_current_user_and_never_role_or_username(self):
        user = self.make_user()
        other = User.objects.create_user(username='other', first_name='Original')
        self.client.force_login(user)
        response = self.client.post('/profile/', {
            'first_name': 'Updated', 'last_name': 'Name', 'email': 'updated@example.com',
            'phone_number': '9811111111', 'address': 'Pokhara',
            'role': 'OWNER', 'username': 'hacked', 'id': other.pk,
        })
        self.assertRedirects(response, '/profile/')
        user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertEqual(user.username, 'customer')
        self.assertEqual(user.first_name, 'Updated')
        self.assertEqual(user.address, 'Pokhara')
        self.assertEqual(user.email, 'updated@example.com')
        self.assertEqual(other.first_name, 'Original')

    def test_profile_invalid_email_is_rejected(self):
        user = self.make_user()
        self.client.force_login(user)
        response = self.client.post('/profile/', {'email': 'bad-email'})
        self.assertIn('email', response.context['form'].errors)

    def test_auth_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/register/', self.registration_data()).status_code, 403)
        self.assertEqual(client.post('/login/', {}).status_code, 403)

