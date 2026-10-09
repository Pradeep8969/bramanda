# Customer email in local development

Customer signup still schedules one text/HTML welcome email after database commit.
Normal registration and Google/Facebook signup use the same helper; returning login
does not send another welcome. SMTP/backend failures and zero-message results log
sanitized errors and do not prevent account creation. Allauth's other account email
features are preserved. Order invoices and receipts remain available as web pages.

The default mailer is Django's console backend. Local signup needs no Gmail
credentials or network connection; messages appear in the development terminal.
The project loads optional `.env` values without executing commands or expanding
variables. Existing process variables take precedence. `.env` remains Git-ignored.
Copy `.env.example` only if you want local overrides; no `.env` is required.

```dotenv
DEBUG=True
PUBLIC_BASE_URL=http://127.0.0.1:8000
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL="BRAMANDA <no-reply@example.com>"
```

`PUBLIC_BASE_URL` supplies welcome links and eSewa callback origins; keep it set to
the address used to access the local application. It accepts an HTTP(S) origin
without a path, credentials, query, or fragment.

## Optional SMTP for existing email features

SMTP is retained because welcome emails and allauth account emails also use it.
To use a provider, explicitly set `EMAIL_BACKEND` to
`django.core.mail.backends.smtp.EmailBackend` and configure `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, and optionally `EMAIL_TIMEOUT`.
These environment values populate Django 6.1's `MAILERS.default.OPTIONS`.

Port 465 requires SSL True and TLS False. Port 587 requires SSL False and TLS True.
Never enable both. Store credentials privately in `.env` or process variables;
never put them in source or chat. Console mode ignores SMTP options.

The former SMTP troubleshooting command and customer password recovery feature
have been removed. Signup, login, logout, profiles, social authentication, and
allauth's authenticated password change/set pages remain available.

Run automated email/authentication tests without sending real emails:

```powershell
.\venv\Scripts\python.exe manage.py test accounts.test_welcome_email accounts.test_email_config accounts.test_auth_routes
```
