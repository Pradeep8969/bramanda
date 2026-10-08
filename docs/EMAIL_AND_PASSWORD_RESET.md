# Customer email and password recovery

BRAMANDA sends a text/HTML welcome message on customer signup and uses Django's built-in password-reset views for customer recovery. Existing password login, Google/Facebook login, custom User, and management-role permissions are preserved. No order/cart/inventory/payment behavior, model schema, or dependency requirements were changed.

## Welcome email

Normal `/register/` signup calls `accounts.emails.schedule_welcome_email()` once. Allauth signup uses a single `user_signed_up` receiver registered in `AccountsConfig.ready()` with a stable dispatch UID; it calls the same helper. The social adapter does not separately send a welcome email.

The helper requires CUSTOMER and an available email. It schedules delivery with `transaction.on_commit()`, so a rolled-back signup sends nothing. Returning password/social logins and social account connections do not trigger signup delivery. OWNER/STAFF login does not send customer welcome emails. Allauth can separately send its own optional verification email, which is not a second welcome email.

The subject is **Welcome to BRAMANDA – THE UNDISCOVERED**. Both text and HTML include first name (or username), account-creation confirmation, shop/login links, and a note that BRAMANDA never emails passwords. The template context contains no password/hash. Social-only customers initially have an unusable password. An active CUSTOMER with an email may choose a local BRAMANDA password through the verified email reset flow without removing Google/Facebook login or their SocialAccount.

SMTP/network delivery failures are logged without credentials or recipients and do not undo successful registration. Sending is synchronous after commit with a configured timeout; there is no durable queue, retry/outbox, or delivery guarantee. Do not manually invoke the helper on repeated login events. A production email queue/retry mechanism with idempotent delivery is a possible deployment extension.

## Required customer email

Password-based customer registration now requires a valid email, strips whitespace, and stores a lowercase value. Case-insensitive validation checks existing local users of every role before creating a new account. It does not rewrite existing records, modify ProfileForm, or introduce a database uniqueness constraint. Existing allauth duplicate-email protections remain intact. Allauth's additional password signup also requires email, while social signup keeps email optional if a provider cannot supply it.

Application-level duplicate validation does not provide a database-level guarantee against simultaneous submissions or external/admin writes. Historical duplicate addresses are not automatically merged or repaired. Django can send one reset message for each eligible pre-existing account with the same address. Review such historical data administratively before production rather than automatically changing users.

## Forgot-password flow

| URL | Built-in Django view |
| --- | --- |
| `/forgot-password/` | PasswordResetView with a customer-filtering PasswordResetForm |
| `/password-reset/done/` | PasswordResetDoneView |
| `/reset/<uidb64>/<token>/` | PasswordResetConfirmView |
| `/reset/done/` | PasswordResetCompleteView |

The customer login page retains both social options and its password form, with a Forgot password? link. A syntactically valid known or unknown email reaches the same message: “If an eligible BRAMANDA account exists for that email address, password instructions have been sent.” Unknown, inactive, non-CUSTOMER, and email-less users receive no reset email through this customer flow. CustomerPasswordResetForm explicitly queries active CUSTOMER accounts by case-insensitive email, preserving Django's Unicode comparison without calling its default get_users(), which excludes unusable passwords. A usable local password or SocialAccount is not required. The user chooses the password on Django's secure confirmation page; no random/default password or duplicate account is created. Existing SocialAccount records remain connected, so both password and Google/Facebook login work afterward. Invalid email syntax is handled as a form validation error, not an account-existence check.

Reset messages include text and HTML, a link/button, and no password. Django signs the time-limited token using the project's secret key and user state. `PASSWORD_RESET_TIMEOUT` is one hour. Password change invalidates the token, password validators remain enabled, and the old password stops working. The confirmation view moves the token into the session before displaying the password form, limiting URL exposure. Reset does not automatically log the user in or change role/privilege flags. Request/confirmation POSTs retain CSRF protection. Existing OWNER/STAFF authentication remains separate and unchanged.

Email links use the configured trusted `PUBLIC_BASE_URL`, rather than the request Host header. Set it to the real HTTPS origin in production. Keep your Django secret private and persistent, configure secure cookies and valid hosts, and rate-limit recovery requests at the deployment edge. Generic responses prevent content-based account enumeration; synchronous SMTP can still introduce timing differences. A queue and abuse controls are recommended for high-volume production deployments. See [Django authentication documentation](https://docs.djangoproject.com/en/6.1/topics/auth/default/).

## Environment configuration

The project reads process environment variables with `os.environ`; it does not automatically load `.env` and does not use python-dotenv. Django 6.1 uses `MAILERS` and rejects defining legacy EMAIL_* Django settings alongside it. These conventional **environment variable names** are mapped into `MAILERS['default']`, including SMTP OPTIONS. Changing only `settings.EMAIL_HOST` at runtime is not this configuration's supported setup mechanism.

| Environment variable | Default / purpose |
| --- | --- |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend`; console backend available for development |
| `EMAIL_HOST` | `smtp.gmail.com` |
| `EMAIL_PORT` | `587` |
| `EMAIL_USE_TLS` | `True` (STARTTLS) |
| `EMAIL_USE_SSL` | `False`; do not enable together with TLS |
| `EMAIL_HOST_USER` | Empty; set the SMTP account username |
| `EMAIL_HOST_PASSWORD` | Empty; set an SMTP/App Password through a secret store or process environment |
| `DEFAULT_FROM_EMAIL` | SMTP username if supplied; otherwise a placeholder BRAMANDA sender. Configure a verified real sender before SMTP use. |
| `EMAIL_TIMEOUT` | `10` seconds |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000`; HTTP(S) origin only, without path, query, fragment, or embedded credentials |

For development without sending real email:

```powershell
$env:EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:8000'
.\venv\Scripts\python.exe manage.py runserver
```

Reset links appear in the local console. Treat them as sensitive and do not publish console logs. Restart the server after changing the environment. Use the same PowerShell session to launch Django; a separately started terminal/server will not inherit these session variables.

## Gmail SMTP development setup

1. Choose a Gmail sender account and enable Google Account **2-Step Verification**.
2. Open [App Passwords](https://myaccount.google.com/apppasswords), authenticate, and generate an app password named BRAMANDA Development. Use this app password for SMTP instead of the normal Google password. App-password availability depends on account policies and security configuration; if unavailable, use an approved transactional provider rather than weakening account security. See [Google App Password guidance](https://support.google.com/mail/answer/185833).
3. Configure the following in PowerShell, replacing only the sender placeholders:

   ```powershell
   $env:EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
   $env:EMAIL_HOST = 'smtp.gmail.com'
   $env:EMAIL_PORT = '587'
   $env:EMAIL_USE_TLS = 'True'
   $env:EMAIL_USE_SSL = 'False'
   $env:EMAIL_HOST_USER = 'your-sender@gmail.com'
   $env:DEFAULT_FROM_EMAIL = 'BRAMANDA <your-sender@gmail.com>'
   $env:EMAIL_TIMEOUT = '10'
   $env:PUBLIC_BASE_URL = 'http://127.0.0.1:8000'
   ```

4. Enter the App Password through a hidden prompt, avoiding a literal password in shell history or source:

   ```powershell
   $smtpCredential = Get-Credential -UserName $env:EMAIL_HOST_USER -Message 'Enter the Gmail App Password'
   $env:EMAIL_HOST_PASSWORD = $smtpCredential.GetNetworkCredential().Password
   ```

5. Run Django from that session. Gmail limits and account policy apply; successful application submission is not proof of inbox delivery. Check spam and sender/provider logs.

Never commit a Gmail password, App Password, environment export, SMTP credentials, or an OAuth secret. SMTP authentication and Google OAuth login use separate credentials; do not substitute OAuth Client Secret for an SMTP App Password.

## Test one real email manually

After configuring SMTP, run:

```powershell
.\venv\Scripts\python.exe manage.py shell
```

In the Django shell, replace the recipient with an address you control:

```python
from django.core.mail import send_mail
send_mail('BRAMANDA email test', 'BRAMANDA SMTP configuration test.', None, ['your-test-recipient@example.com'])
```

This sends one real email. A return value of 1 indicates backend acceptance, not guaranteed inbox delivery. Then register a new customer using a unique email to test the welcome message, and submit `/forgot-password/` for that customer to test recovery end to end. Test a local-password account and a Google/Facebook-only customer. Check the branded HTML/text versions, confirm the old local password fails after reset, and confirm a social customer can sign in with both the chosen password and the original provider afterward. No real email was sent by the implementation/automated tests.

## Production delivery

Prefer a transactional provider such as Amazon SES, SendGrid, Mailgun, Brevo, or Postmark over a personal Gmail account. Use that provider's SMTP host/port/credentials and a verified sender; configure SPF/DKIM and DMARC as instructed by the provider. Use a deployment secret manager, the actual HTTPS `PUBLIC_BASE_URL`, request rate limits, failure/bounce monitoring, and an appropriate retry/queue policy. The current Django development settings (including DEBUG and checked-in development secret) also require production configuration; this task does not deploy the application.

## Automated testing

Tests use Django's locmem mailer and never contact Gmail or another SMTP server. Social OAuth remains mocked with its network guard. New coverage checks required/normalized/duplicate email, one-time welcome triggers and rollback, SMTP failure handling, both social providers, role preservation, generic recovery responses, first-password creation for both social providers, retained SocialAccounts and dual login, active CUSTOMER eligibility, signed valid/invalid/expired/reused tokens, password changes, validators, CSRF, and trusted email-link origin.

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
git status --short
```

Verified on 2026-10-08: system check passed, all 232 tests passed (228 previous baseline + 4 additional tests), migration dry-run reported no changes, and `git diff --check` passed. No model migration, package installation, or real SMTP send was required.
