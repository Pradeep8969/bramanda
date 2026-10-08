# Google and Facebook customer sign in

BRAMANDA uses django-allauth 65.19.7 for Google/Facebook OAuth while retaining its existing `/login/`, `/register/`, `/logout/`, and `/profile/` views. The custom user remains `accounts.User`. No BRAMANDA model or migration is changed.

## Local installation

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

`requirements.txt` pins the direct runtime dependencies observed in the environment: Django 6.1.1, Pillow 12.3.0, and `django-allauth[socialaccount]` 65.19.7. The extra installs the required OAuth, HTTP, JWT, and cryptography dependencies. Allauth's packaged account/socialaccount migrations were applied locally; there is no new BRAMANDA migration.

## Credentials: Django admin only

This project uses database-backed **SocialApp** records. There are no OAuth credentials in settings and no environment-variable credential configuration to maintain alongside it. Do not add `APP`/`APPS` credentials to `SOCIALACCOUNT_PROVIDERS` as well: multiple matching applications can cause ambiguous app lookup.

1. Start the server and sign in to `http://127.0.0.1:8000/admin/` with a Django superuser (or an administrator having SocialApp permissions). The application OWNER role alone does not grant Django admin access.
2. Under **Social Accounts → Social applications**, select **Add social application**. The direct add route is `/admin/socialaccount/socialapp/add/`.
3. Create exactly one record per provider using the table below.
4. Leave **Provider ID**, **Key**, and optional **Settings** blank/default. Provider ID is for subproviders, not the Google/Facebook provider slug. Do not override verified-email or email-authentication behavior in this field.
5. Save. Reload `/login/` or `/register/`; configured providers become POST sign-in buttons. With no records, both buttons are disabled and password forms continue to work. With only one configured provider, only that provider is offered.

| Admin field | Google record | Facebook record |
| --- | --- | --- |
| Provider | Google (internal provider slug `google`) | Facebook (internal provider slug `facebook`) |
| Provider ID | Leave blank | Leave blank |
| Name | BRAMANDA Google | BRAMANDA Facebook |
| Client id | OAuth Client ID from Google Cloud | App ID from Meta |
| Secret key | OAuth Client Secret from Google Cloud | App Secret from Meta |
| Key | Leave blank | Leave blank |
| Settings | Leave default `{}` | Leave default `{}` |
| Sites | Not present / not required | Not present / not required |

Secrets are stored in the local database, not Git-tracked source. `db.sqlite3` and its journal files are already ignored by `.gitignore`. Do not commit database dumps, OAuth client JSON downloads, or screenshots containing credentials. No real credentials or SocialApp records were created during implementation.

## Why Sites / SITE_ID is not required

This conclusion is based on the installed 65.19.7 implementation, not a legacy setup example:

- `allauth.app_settings.SITES_ENABLED` checks whether `django.contrib.sites` is installed. It is not installed in BRAMANDA.
- `SocialAppManager.on_site()` in `allauth/socialaccount/models.py` returns all SocialApp records when Sites is disabled; it filters a Site relationship only when Sites is enabled.
- The SocialApp `sites` field and admin Site selector are declared conditionally. Neither is present in this configuration.
- Automated tests verify database SocialApp lookup and the admin form without Sites.

Therefore, **do not add `django.contrib.sites` or SITE_ID for this single-site setup**. No local Site record or Site association is necessary. Callback hosts are built from the actual request, so browse consistently at `127.0.0.1:8000`. If a future deployment deliberately enables Sites, it will need Sites migrations, a configured domain/SITE_ID or request-based Site resolution, and SocialApp Site associations; that is a different configuration.

## Google Cloud: manual setup

1. Open [Google Cloud Console](https://console.cloud.google.com/), select or create the BRAMANDA project, and open **Google Auth Platform** (older menus call this **APIs & Services → OAuth consent screen**).
2. Configure the consent app/branding: BRAMANDA name, support email, and developer contact email. Choose **External** for customer Google accounts; an organization-only Internal app will not accept arbitrary customers.
3. In Audience, keep the app in testing for the college demo and add the Google accounts that will test it. Complete any consent-screen fields required by the console. For public production access, complete the applicable publishing/verification requirements.
4. Use only basic identity data access: email and profile. BRAMANDA requests `profile` and `email`; it does not request Drive, contacts, offline access, or other business permissions.
5. Open **Clients → Create client** (or **Credentials → Create Credentials → OAuth client ID**). Select **Web application**, name it BRAMANDA Local, and add this exact **Authorized redirect URI**:

   ```text
   http://127.0.0.1:8000/accounts/google/login/callback/
   ```

6. This is server-side OAuth; an Authorized JavaScript origin is not needed by the implementation. If configuring a separate browser integration later, that would require its own origin setup.
7. Create the client and securely copy its Client ID and Client Secret into the Google SocialApp record described above. Do not put the downloaded client JSON in the repository.
8. Visit `/login/` at `http://127.0.0.1:8000`, select **Continue with Google**, and authenticate using an allowed test account. A new customer should reach `/shop/` or a validated customer `next` destination.

Google requires the callback to match the configured URI exactly, including scheme, host, port, path, and trailing slash. `localhost` is a different host from `127.0.0.1`; register a separate URI if you choose to browse there. See [Google web-server OAuth documentation](https://developers.google.com/identity/protocols/oauth2/web-server).

## Meta for Developers: manual setup

1. Open [Meta for Developers](https://developers.facebook.com/apps/), register a developer account if needed, and create a BRAMANDA app. Choose the consumer **Authenticate and request data from users with Facebook Login** use case / Facebook Login product for website users. Do not select an unrelated marketing or business-login integration.
2. Supply the app name and contact email. In the Facebook Login use case customization (or **Facebook Login → Settings** in the product menu), enable **Client OAuth Login** and **Web OAuth Login**. Keep strict redirect-URI matching enabled.
3. Configure the Web platform / website URL as `http://127.0.0.1:8000/` for local development if Meta accepts it. In **Valid OAuth Redirect URIs**, enter the exact development callback:

   ```text
   http://127.0.0.1:8000/accounts/facebook/login/callback/
   ```

4. Request only `public_profile` and `email`. BRAMANDA uses the server-side OAuth2 flow, not the Facebook JavaScript SDK. It fetches ID, first/last name, name, and email; Facebook may omit email if the user has no available email or declines access.
5. Keep the app in development mode for testing. Add the people demonstrating the project under the app's roles/testers and have them accept the invitation. Development-mode login is restricted by Meta to eligible app-role/test accounts.
6. In **App settings → Basic**, copy **App ID** into the Facebook SocialApp **Client id** and reveal/copy **App Secret** into **Secret key**. Do not put either secret or an exported configuration in the repository.
7. Visit `/login/` and select **Continue with Facebook** using an eligible tester account. Confirm that signup creates a customer and returning login uses the same local account.
8. Before making the app available to the public, complete Meta's current app requirements, including relevant privacy-policy/data-deletion information, app review/access approval, verification if required, and live/publish configuration. These external requirements are not implemented app features.

Meta's menu labels and local HTTP/IP acceptance can differ by app type and current console policy. The callback above is BRAMANDA's exact local route, but acceptance of `http://127.0.0.1` has not been verified in a real Meta app. If Meta rejects it, use an approved HTTPS development domain/tunnel, register `https://<development-domain>/accounts/facebook/login/callback/`, and browse BRAMANDA through that same origin. Configure allowed hosts and HTTPS/proxy settings for that environment; do not weaken OAuth URI validation or CSRF settings. Consult [Meta Facebook Login documentation](https://developers.facebook.com/docs/facebook-login/) and [allauth Facebook configuration](https://docs.allauth.org/en/latest/socialaccount/providers/facebook.html).

## Production callbacks

Register the real HTTPS production domain with each provider, for example:

```text
https://<production-domain>/accounts/google/login/callback/
https://<production-domain>/accounts/facebook/login/callback/
```

Use production credentials in that deployment's SocialApp records. Configure Django's production secret, DEBUG, allowed hosts, secure cookies, and trusted proxy/HTTPS handling separately. Never register an HTTP production callback or treat the loopback development URLs as production URLs.

## Signup, returning users, and email conflicts

- First-time provider authentication runs allauth auto-signup when its data is sufficient and conflict-free. It stores available first/last name and email, generates a valid unique username as needed, and sets an unusable password. No BRAMANDA password is required for social signup.
- `CustomerSocialAccountAdapter.save_user()` explicitly assigns CUSTOMER and clears `is_staff`/`is_superuser` on a new user. It does not run during returning login or connection to an existing account, and does not overwrite existing STAFF/OWNER roles or passwords.
- A returning provider identity is matched by provider and UID, not by an untrusted email address. The existing customer logs in without a duplicate user.
- `SOCIALACCOUNT_EMAIL_AUTHENTICATION` and `SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT` remain False. No provider-level override is configured. A same-email match does not silently authenticate or merge an existing normal account, even for a Google-verified email.
- Allauth's unique-email defaults detect existing emails in both the custom User and EmailAddress records. A conflict redirects to `/accounts/3rdparty/signup/`. Submitting the conflicting email shows a validation error and creates neither a user nor an automatic connection. This does not retroactively impose email uniqueness on BRAMANDA's existing password forms or model.
- To connect legitimately: sign in at `/login/` with the existing BRAMANDA credentials, open `/accounts/3rdparty/`, and choose the provider under the account-connection controls. Allauth starts `process=connect` using a POST confirmation. After completing OAuth, the social identity belongs to the already authenticated account. A different email should be supplied for a separate new account rather than using an existing account's email.
- If information needs confirmation, the social signup form contains username/email fields, not password fields. Email remains optional for social signup, while new password-based signup requires email. Facebook does not establish verified ownership merely from its profile's `verified` value; that trust is not overridden. Allauth's optional email verification defaults are retained. Customer signup now sends a welcome message when email is available; configure SMTP or the console mailer as described in [Email and password reset](EMAIL_AND_PASSWORD_RESET.md).

## Security and redirects

Provider initiation on BRAMANDA login/register pages uses POST forms with CSRF tokens. `SOCIALACCOUNT_LOGIN_ON_GET = False`; a direct GET displays allauth's confirmation page instead of initiating OAuth. Provider callbacks necessarily use GET with allauth's session-bound state validation. Forged callback state is rejected, and tests do not bypass it.

`CustomerAccountAdapter.is_safe_url()` retains allauth's host/scheme checks and additionally rejects management namespaces (owner, dashboard, admin) and unresolved destinations. The normal fallback is the existing `LOGIN_REDIRECT_URL`, `/shop/`. Safe customer destinations such as `/cart/` are preserved. Existing Django password login retains its own safe `next` behavior and normal STAFF/OWNER access. No order, cart, inventory, or dashboard business logic is modified.

## Verification and remaining manual checks

`accounts/test_social_auth.py` exercises real POST initiation and callback/state processing with mocked token exchange and provider identity data. A network guard fails tests if an HTTP request escapes a mock. Tests cover both providers, password registration/login, no-credential pages, SocialApp/admin forms, customer-only signup, returning accounts, existing role preservation, duplicate-email conflicts, explicit connection, redirects, CSRF, and anonymous behavior.

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
git diff --check
git status --short
```

Provider projects, real credentials, consent-screen configuration, live OAuth access, and desktop/mobile visual review must be completed manually. Automated tests do not contact Google or Facebook. No OAuth secret has been entered or committed by this task.

Verified locally on 2026-10-07: system check passed, all 204 tests passed (179 existing + 25 social tests), migration dry-run reported no changes, `pip check` reported no broken requirements, and `git diff --check` passed. Existing unrelated owner UI changes in the working tree were preserved.
