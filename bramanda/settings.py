"""
Django settings for BRAMANDA – THE UNDISCOVERED.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


from .email_config import load_local_env, smtp_config

BASE_DIR = Path(__file__).resolve().parent.parent
load_local_env(BASE_DIR / ".env")


# ============================================================
# SECURITY AND ENVIRONMENT
# ============================================================

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "django-insecure-local-development-only-"
    "bramanda-replace-with-environment-secret"
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.1.72"]
CSRF_TRUSTED_ORIGINS = []


# ============================================================
# APPLICATIONS
# ============================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.facebook",

    "accounts",
    "products",
    "cart",
    "orders",
    "payments",
    "inventory",
    "dashboard",
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "bramanda.urls"


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cart.context_processors.cart_counter",
            ],
        },
    },
]


WSGI_APPLICATION = "bramanda.wsgi.application"


# ============================================================
# DATABASE
# ============================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
}


# ============================================================
# PASSWORD VALIDATION
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ============================================================
# INTERNATIONALIZATION
# ============================================================

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"

USE_I18N = True
USE_TZ = True


# ============================================================
# STATIC AND MEDIA FILES
# ============================================================

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# USER AUTHENTICATION
# ============================================================

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "products:shop"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]


# ============================================================
# DJANGO-ALLAUTH
# ============================================================

ACCOUNT_ADAPTER = "accounts.adapters.CustomerAccountAdapter"

ACCOUNT_LOGIN_METHODS = {"username"}

ACCOUNT_SIGNUP_FIELDS = [
    "username*",
    "email*",
    "password1*",
    "password2*",
]

SOCIALACCOUNT_EMAIL_REQUIRED = False

SOCIALACCOUNT_ADAPTER = (
    "accounts.adapters.CustomerSocialAccountAdapter"
)

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = False

SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = False

# Google/Facebook credentials remain in SocialApp records.
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
            "prompt": "select_account",
        },
        "OAUTH_PKCE_ENABLED": True,
    },
    "facebook": {
        "METHOD": "oauth2",
        "SCOPE": [
            "email",
            "public_profile",
        ],
    },
}


# ============================================================
# EMAIL CONFIGURATION - DJANGO 6.1
# ============================================================

_config_email_backend = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)

_smtp_options = (
    smtp_config(os.environ)
    if _config_email_backend == "django.core.mail.backends.smtp.EmailBackend"
    else {}
)
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    _smtp_options.get("username") or "BRAMANDA <no-reply@example.com>",
)
MAILERS = {
    "default": {
        "BACKEND": _config_email_backend,
        "OPTIONS": _smtp_options
        if _config_email_backend == "django.core.mail.backends.smtp.EmailBackend"
        else {},
    },
}


# ============================================================
# PUBLIC WEBSITE URL
# ============================================================

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

_public_origin = urlsplit(PUBLIC_BASE_URL)

if (
    _public_origin.scheme not in ("http", "https")
    or not _public_origin.netloc
    or _public_origin.username
    or _public_origin.password
    or _public_origin.path
    or _public_origin.query
    or _public_origin.fragment
):
    raise ImproperlyConfigured(
        "PUBLIC_BASE_URL must be an HTTP(S) origin "
        "without a path or credentials."
    )


# ============================================================
# ESEWA EPAY V2 TEST/UAT
# ============================================================

ESEWA_ENV = os.environ.get(
    "ESEWA_ENV",
    "test",
).lower()

ESEWA_PRODUCT_CODE = os.environ.get(
    "ESEWA_PRODUCT_CODE",
    "EPAYTEST",
)

# Published eSewa UAT signing key.
# Never put a real production merchant secret here.
ESEWA_SECRET_KEY = os.environ.get(
    "ESEWA_SECRET_KEY",
    "8gBm/:&EnhH.1/q",
)

ESEWA_PAYMENT_URL = os.environ.get(
    "ESEWA_PAYMENT_URL",
    "https://rc-epay.esewa.com.np/api/epay/main/v2/form",
)

ESEWA_STATUS_URL = os.environ.get(
    "ESEWA_STATUS_URL",
    "https://uat.esewa.com.np/api/epay/transaction/status/",
)

if (
    ESEWA_ENV not in ("test", "uat")
    or ESEWA_PRODUCT_CODE != "EPAYTEST"
    or ESEWA_PAYMENT_URL
    != "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
    or ESEWA_STATUS_URL
    != "https://uat.esewa.com.np/api/epay/transaction/status/"
):
    raise ImproperlyConfigured(
        "Only official eSewa ePay V2 TEST/UAT "
        "configuration is supported."
    )
