
"""
Django settings for BRAMANDA – THE UNDISCOVERED.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# SECURITY AND ENVIRONMENT
# ============================================================

IS_VERCEL = os.environ.get("VERCEL") == "1"

DEBUG = os.environ.get(
    "DEBUG",
    "False" if IS_VERCEL else "True",
).lower() in ("true", "1", "yes")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")

if not SECRET_KEY:
    if IS_VERCEL:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be configured in Vercel "
            "environment variables."
        )

    # Local development only. Never use this fallback in production.
    SECRET_KEY = (
        "django-insecure-local-development-only-"
        "bramanda-replace-with-environment-secret"
    )


# ============================================================
# ALLOWED HOSTS AND CSRF
# ============================================================

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "192.168.1.72",
    "bramanda-beta.vercel.app",
]

CSRF_TRUSTED_ORIGINS = [
    "https://bramanda-beta.vercel.app",
]

# Support Vercel's generated deployment/preview domain.
VERCEL_URL = os.environ.get("VERCEL_URL", "").strip()

if VERCEL_URL:
    if (
        "/" in VERCEL_URL
        or ":" in VERCEL_URL
        or " " in VERCEL_URL
        or not VERCEL_URL.endswith(".vercel.app")
    ):
        raise ImproperlyConfigured(
            "VERCEL_URL must be a valid Vercel hostname."
        )

    if VERCEL_URL not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(VERCEL_URL)

    CSRF_TRUSTED_ORIGINS.append(
        f"https://{VERCEL_URL}"
    )

# Vercel terminates HTTPS at its proxy.
if IS_VERCEL:
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )

SESSION_COOKIE_SECURE = IS_VERCEL
CSRF_COOKIE_SECURE = IS_VERCEL


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

# Local development database.
# NOTE: SQLite is not suitable as persistent database storage
# for a live Vercel serverless e-commerce deployment.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
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
    "django.core.mail.backends.smtp.EmailBackend",
)

_config_email_host = os.environ.get(
    "EMAIL_HOST",
    "smtp.gmail.com",
)

_config_email_port = int(
    os.environ.get("EMAIL_PORT", "587")
)

_config_email_use_tls = os.environ.get(
    "EMAIL_USE_TLS",
    "True",
).lower() in ("true", "1", "yes")

_config_email_use_ssl = os.environ.get(
    "EMAIL_USE_SSL",
    "False",
).lower() in ("true", "1", "yes")

_config_email_host_user = os.environ.get(
    "EMAIL_HOST_USER",
    "",
)

_config_email_host_password = os.environ.get(
    "EMAIL_HOST_PASSWORD",
    "",
)

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    _config_email_host_user
    or "BRAMANDA <no-reply@example.com>",
)

_config_email_timeout = int(
    os.environ.get("EMAIL_TIMEOUT", "10")
)

MAILERS = {
    "default": {
        "BACKEND": _config_email_backend,
        "OPTIONS": {
            "host": _config_email_host,
            "port": _config_email_port,
            "username": _config_email_host_user,
            "password": _config_email_host_password,
            "use_tls": _config_email_use_tls,
            "use_ssl": _config_email_use_ssl,
            "timeout": _config_email_timeout,
        }
        if _config_email_backend
        == "django.core.mail.backends.smtp.EmailBackend"
        else {},
    },
}


# ============================================================
# PUBLIC WEBSITE URL
# ============================================================

PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    (
        "https://bramanda-beta.vercel.app"
        if IS_VERCEL
        else "http://127.0.0.1:8000"
    ),
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

PASSWORD_RESET_TIMEOUT = 3600


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
