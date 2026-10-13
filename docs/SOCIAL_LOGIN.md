# Google customer sign in

BRAMANDA retains django-allauth, Google OAuth and existing email/password login and signup. OAuth initiation uses POST with CSRF protection. No automatic email-based account linking is enabled.

## Google setup

Create a Google web OAuth client and register exactly `http://127.0.0.1:8000/accounts/google/login/callback/`. Configure its consent screen and allowed test users. In Django admin, create one SocialApp with provider `google`, blank Provider ID, Google client ID and secret, and default settings. Credentials stay in the database; do not put them in templates, source or logs. Sites/SITE_ID is not needed for this installed configuration. Without a configured SocialApp, password authentication remains available and the Google button is disabled.

Use the same browser origin for checkout and OAuth. Test Google consent manually with an authorized test account; automated tests mock OAuth exchange and do not contact Google.

## Historical Facebook-linked accounts

Facebook is no longer an active provider; initiation and callback URLs return 404. No SocialApp, SocialAccount, SocialToken, user, session, order or payment records are deleted. Historical credentials are inactive; authorized administrators may rotate/revoke them with the provider separately.

Customers with an existing usable password or already connected Google identity can use those methods. A customer who still has a trusted authenticated session may use allauth's password-set or explicit Google connection flow. Facebook-only customers without an authenticated session require support to verify account ownership through an established trusted channel and issue an audited recovery process. Automated recovery for these users is not added here, and password-reset routes remain disabled. Never set a shared password or attach a Google account merely because an unverified email matches. Keep historical identity evidence and do not merge accounts automatically.
