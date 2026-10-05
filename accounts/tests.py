from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse


class FoundationTests(TestCase):
    def test_custom_user_defaults_and_password(self):
        user = get_user_model().objects.create_user(
            username='customer', password='college-test-password',
            phone_number='9800000000', address='Kathmandu',
        )
        user.refresh_from_db()
        self.assertEqual(user.role, 'CUSTOMER')
        self.assertEqual(user.phone_number, '9800000000')
        self.assertEqual(user.address, 'Kathmandu')
        self.assertTrue(user.check_password('college-test-password'))

    def test_roles_are_validated(self):
        for role in ('OWNER', 'STAFF', 'CUSTOMER'):
            user = get_user_model()(username=role.lower(), role=role)
            user.set_unusable_password()
            user.full_clean()
        user.role = 'INVALID'
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_homepage(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertTemplateUsed(response, 'base.html')
        for text in ('BRAMANDA', 'THE UNDISCOVERED', 'Shop Now', 'Featured essentials',
                     'Home', 'Shop', 'Cart', 'Login', 'Register'):
            self.assertContains(response, text)
