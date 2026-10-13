from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

PASSWORD = "Role-Login-Password-845!"


class RoleLoginRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.owner = users.create_user(
            username="redirect-owner", password=PASSWORD, role="OWNER"
        )
        cls.staff = users.create_user(
            username="redirect-staff", password=PASSWORD, role="STAFF"
        )
        cls.customer = users.create_user(
            username="redirect-customer", password=PASSWORD, role="CUSTOMER"
        )
        cls.admin_customer = users.create_user(
            username="redirect-admin",
            password=PASSWORD,
            role="CUSTOMER",
            is_staff=True,
            is_superuser=True,
        )

    def sign_in(self, user, next_url=None, route="accounts:login"):
        self.client.logout()
        data = {
            "login" if route == "account_login" else "username": user.username,
            "password": PASSWORD,
        }
        if next_url is not None:
            data["next"] = next_url
        return self.client.post(reverse(route), data)

    def test_default_destinations_and_established_sessions(self):
        for user, name in (
            (self.owner, "owner:home"),
            (self.staff, "dashboard:home"),
            (self.customer, "home"),
            (self.admin_customer, "home"),
        ):
            with self.subTest(role=user.username):
                response = self.sign_in(user)
                self.assertRedirects(response, reverse(name))
                self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_generic_storefront_next_does_not_override_management_defaults(self):
        for user, name in ((self.owner, "owner:home"), (self.staff, "dashboard:home")):
            for destination in ("/", "/?source=login", "/shop/", "http://testserver/"):
                with self.subTest(role=user.role, destination=destination):
                    self.assertRedirects(self.sign_in(user, destination), reverse(name))

    def test_authorized_next_preserved_with_query_string(self):
        for user, destination in (
            (self.owner, "/owner/inventory/?q=shirt"),
            (self.owner, "/staff/orders/"),
            (self.staff, "/staff/inventory/"),
            (self.customer, "/profile/"),
            (self.customer, "/cart/"),
            (self.customer, "/checkout/"),
        ):
            with self.subTest(destination=destination):
                self.assertRedirects(
                    self.sign_in(user, destination),
                    destination,
                    fetch_redirect_response=False,
                )

    def test_forbidden_management_and_unsafe_urls_fall_back(self):
        for user, name in (
            (self.owner, "owner:home"),
            (self.staff, "dashboard:home"),
            (self.customer, "home"),
        ):
            destinations = [
                "https://evil.example/",
                "//evil.example/",
                "/\\evil.example/",
                "/%2f%2fevil.example/",
                "/unknown/",
                "/login/",
                "/accounts/login/",
                "/logout/",
                "/accounts/google/login/",
                "/owner/inventory/update/",
            ]
            if user.role != "OWNER":
                destinations += ["/owner/", "/%6fwner/", "/owner/inventory/"]
            if user.role == "CUSTOMER":
                destinations += ["/staff/"]
            for destination in destinations:
                with self.subTest(role=user.role, destination=destination):
                    self.assertRedirects(self.sign_in(user, destination), reverse(name))

    def test_dashboard_permissions_unchanged(self):
        self.client.logout()
        for name in ("owner:home", "dashboard:home"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                response.url.startswith(reverse("accounts:login") + "?next=")
            )
        self.sign_in(self.customer)
        self.assertEqual(self.client.get(reverse("owner:home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)
        self.sign_in(self.staff)
        self.assertEqual(self.client.get(reverse("owner:home")).status_code, 403)

    def test_invalid_credentials_never_redirect_or_start_session(self):
        for user in (self.owner, self.staff, self.customer):
            response = self.client.post(
                reverse("accounts:login"),
                {
                    "username": user.username,
                    "password": "wrong",
                    "next": reverse("owner:home"),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_then_login_and_authenticated_login_have_no_loops(self):
        for user, name in (
            (self.owner, "owner:home"),
            (self.staff, "dashboard:home"),
            (self.customer, "home"),
        ):
            self.sign_in(user)
            self.assertRedirects(
                self.client.get(reverse("accounts:login")), reverse(name)
            )
            self.assertRedirects(
                self.client.post(reverse("accounts:logout")), reverse("home")
            )
            self.assertNotIn("_auth_user_id", self.client.session)
            self.assertRedirects(
                self.sign_in(user, reverse("accounts:login")), reverse(name)
            )

    def test_allauth_password_login_uses_shared_policy(self):
        for user, name in (
            (self.owner, "owner:home"),
            (self.staff, "dashboard:home"),
            (self.customer, "home"),
        ):
            self.assertRedirects(
                self.sign_in(user, route="account_login"), reverse(name)
            )

    def test_next_from_get_and_post_precedence(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=/owner/inventory/",
            {"username": self.owner.username, "password": PASSWORD},
        )
        self.assertRedirects(response, reverse("owner:inventory"))
        self.client.logout()
        response = self.client.post(
            reverse("accounts:login") + "?next=/owner/inventory/",
            {
                "username": self.owner.username,
                "password": PASSWORD,
                "next": "/owner/orders/",
            },
        )
        self.assertRedirects(response, reverse("owner:orders"))
