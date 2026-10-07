# Testing

## Strategy

The project uses Django's built-in test runner and `django.test.TestCase`. Test cases create controlled users, catalog entries, carts, and orders in an isolated test database. Django's test client exercises HTTP pages, redirects, forms, authentication, and authorization. Direct model/service tests verify constraints, totals, inventory history, and rollback behavior. Selected tests use `Client(enforce_csrf_checks=True)` because CSRF enforcement is otherwise disabled by the standard test client.

Mocked write failures exercise transaction rollback. Sequential final-stock and stale-instance tests cover stock safety, but they do not establish production-scale concurrent-load performance.

## Areas covered by actual tests

| Test modules | Important coverage |
| --- | --- |
| `accounts/tests.py`, `accounts/test_customer_auth.py` | Custom user defaults and roles, homepage, registration, hashed passwords, fixed CUSTOMER role, password validation, duplicate username, login/safe next, inactive login denial, POST logout, own profile editing, restricted fields, CSRF |
| `accounts/test_social_auth.py` | Google/Facebook POST initiation and mocked callbacks, CSRF/state validation, auto-signup and returning login, CUSTOMER/privilege enforcement, no-credential pages, SocialApp/admin configuration without Sites, duplicate email rejection, explicit account connection, redirects, preserved password login/registration and management roles |
| `products/tests.py`, `products/test_storefront.py` | Model/form validation, slugs/collisions, unique SKU/variant combination, nonnegative price/stock, reusable seed command, active catalog visibility, search, combined filters, sorting, galleries, featured products, navigation, bounded prefetch query count |
| `cart/tests.py` | Login, account isolation, add/update/remove, quantity/stock limits, inactive variants, computed Decimal totals, untrusted prices, stock warnings, no stock change during cart operations, constraints, POST/CSRF requirements |
| `orders/tests.py` | Checkout authentication/prefill, required shipping fields and COD-only input, server-controlled totals/status/customer, item snapshots, unique order numbers, stock deductions/history/cart clearing, current prices, insufficient-stock and injected-failure rollback, duplicate submission, SQLite conflict handling, own order access, tracking and history preservation |
| `inventory/tests.py` | Stock increases/decreases, zero boundary, negative-stock rejection, transaction-type/sign/input validation, current database stock, rollback when history fails, history-only writes do not alter stock |
| `dashboard/tests.py` | Staff/owner access and customer denial, superuser-role separation, metrics/stock boundaries, order search/filters, status/delivery/COD actions and audit, protected financial/user fields, POST/CSRF, read-only customers, inventory adjustments and audit-failure rollback |
| `dashboard/test_owner.py` | All owner route guards, real login journey, metrics/charts/report calculations and inclusive dates, invalid/empty reports, best sellers/snapshots, catalog editing/toggles, stock field restrictions, staff creation/password/field restrictions/deactivation, owner inventory including inactive variants, shared order operations, payment/activity filters, customer counts, navigation and CSRF |

`payments/tests.py` is a scaffold with no test methods. Payment behavior is tested through orders and dashboard because payment fields live on Order.

## Run the suite

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

With an activated environment, `python` can replace the explicit interpreter path. To focus on an area:

```powershell
python manage.py test accounts products cart orders inventory dashboard
python manage.py test dashboard.test_owner
python manage.py test orders.tests.CheckoutOrderTests
```

## HTTP walkthroughs and responsive checks

`scripts/verify_customer_flow.py`, `scripts/verify_order_flow.py`, and `scripts/verify_staff_dashboard.py` contain additional test-client walkthroughs against local data, using transaction rollback to preserve verification writes. They are not part of normal test discovery. The order script assumes seeded Black/M stock is exactly 20, so it is unsuitable for arbitrary changed data without review.

The earlier `OWNER_DASHBOARD_REPORT.md` records HTTP walkthrough results and explicitly states that visual desktop/mobile review remains outstanding. Viewport metadata, CSS media queries, and responsive interaction code exist, but no browser automation suite or screenshot-based visual test was found. HTTP content/navigation assertions do not prove rendered mobile appearance.

Suggested manual review before submission: inspect storefront/product/cart/checkout/tracking and staff/owner dashboards at desktop and mobile widths; check menu controls, form errors, table scrolling, keyboard interaction, and readability. These are proposed checks, not verified browser results.

## Current verification

The following results were verified on 2026-10-07 using the existing `.\venv\Scripts\python.exe` environment:

| Command | Result |
| --- | --- |
| `manage.py check` | Passed: no issues (0 silenced) |
| `manage.py test` | Passed: 204 tests discovered and run; OK |
| `manage.py makemigrations --check --dry-run` | Passed: No changes detected |

The runner created and destroyed its test database. No BRAMANDA migration files were generated. The current count includes 25 social-auth tests added to the previous 179. OAuth token/profile calls are mocked and an HTTP network guard prevents external requests during social tests. Packaged allauth migrations were applied locally for the social-login feature.

## Information not verified

A complete clean-clone dependency installation, supported Python version range, production deployment, real-provider OAuth access, and visual/browser compatibility were not verified. `requirements.txt` now declares direct dependencies, and installing allauth succeeded locally. No default login credentials exist in the inspected source. Screenshot placeholders remain intentionally empty. Provider setup and remaining manual checks are documented in [Social login](SOCIAL_LOGIN.md).
