# BRAMANDA owner dashboard implementation

## Files created and changed

Created `dashboard/owner_forms.py`, `dashboard/owner_views.py`, `dashboard/owner_urls.py`, and `dashboard/test_owner.py`.
Created owner templates: `base.html`, `home.html`, `reports.html`, `catalog.html`, `form.html`, `staff.html`, `payments.html`, `activity.html`, `_activity.html`, `_best.html`, `orders.html`, `order_detail.html`, `_orders.html`, `customers.html`, `inventory.html`, and `invalid.html`.
Changed `dashboard/permissions.py`, `dashboard/views.py`, `bramanda/urls.py`, `templates/base.html`, and `static/css/base.css`.
No existing apps or models were recreated. Existing product ModelForms are reused.

## URLs

- `/owner/`
- `/owner/reports/`
- `/owner/products/`, `/owner/categories/`, `/owner/sizes/`, `/owner/colors/`, `/owner/variants/`
- Each catalogue section has `/add/`, `/<id>/edit/`, and POST-only `/<id>/toggle/`.
- `/owner/inventory/` and POST-only `/owner/inventory/adjust/`
- `/owner/staff/`, `/owner/staff/add/`, `/owner/staff/<id>/edit/`, POST-only `/owner/staff/<id>/toggle/`
- `/owner/customers/`
- `/owner/orders/`, `/owner/orders/<order_number>/`
- POST-only order endpoints: `/status/`, `/delivery/`, `/payment/`
- `/owner/payments/`
- `/owner/activity/`

## Authorization and security

Reusable `owner_required` checks authenticated, active users with role exactly OWNER. Anonymous users redirect to login with next; CUSTOMER and STAFF receive 403. Superuser and Django is_staff flags do not bypass this role check. Every owner route is guarded server-side, including wrappers around shared staff operations.
Mutations require POST. CSRF middleware remains enabled. Forms whitelist fields: variants cannot edit stock, staff cannot edit role or privilege flags, existing staff cannot edit passwords, and order forms cannot edit money totals or customer assignments.
Owner navigation displays both Owner Dashboard and Staff Dashboard. Staff see only Staff Dashboard; customers see neither.

## Dashboard and analytics

Real database metrics: total revenue, total orders, customers, products, active products, pending/processing/delivered orders, paid orders, low-stock variants, and out-of-stock variants. Also sales/orders today and this month, recent orders, recent inventory activity, recent staff activity, and best sellers.
Revenue is the grand total including shipping of PAID orders excluding CANCELLED orders. Paid order count is the literal count of orders marked PAID. Stock alerts count active variants, using the shared low-stock threshold (1?5); zero stock is counted separately.
Seven-day sales and order bar charts use server-generated values and CSS, with visible dates and numeric values. No external chart dependency.

## Reports

Inclusive local-date From/To filters; invalid dates and reversed ranges show form errors. Revenue and average order value use paid, non-cancelled orders. Number of orders counts non-cancelled orders; delivered and cancelled counts are shown separately. Definitions appear on the page.
Best sellers use OrderItem quantity and stored item subtotal, excluding cancelled orders. Live products group across name changes; deleted product references fall back to snapshot names. Item revenue excludes shipping and includes valid unpaid orders, as explained in the best-seller section.

## Product management

Create, edit, activate/deactivate products, categories, sizes, colors, and variants with existing ModelForms and validation. Product image upload is supported. Variants start with zero stock; stock changes go through inventory only. No delete endpoints were introduced.

## Staff and customer management

Staff creation uses Django UserCreationForm, password validation, and password hashing. The role is always STAFF; submitted OWNER or privilege flags are ignored. Staff list, basic information editing, and activation/deactivation are owner-only. OWNER and CUSTOMER accounts cannot be targeted through staff-edit routes.
Customer list is read-only and includes existing customer information and annotated order counts.

## Inventory and orders

Owner inventory lists all variants, including inactive ones, with SKU, product, size, color, stock, and shared stock-status labels. Owners can adjust inactive variants too. Existing adjust_stock service enforces nonnegative stock, concurrency checks, and InventoryTransaction creation with created_by. Inventory and StaffActivity writes remain atomic.
Owner orders reuse existing staff views and status-update logic, search, filters, snapshot details, delivery updates, and COD paid action. Owner redirects and forms stay within owner routes. Financial totals remain immutable through these forms.

## Payment overview and activity

Payments come directly from orders, showing order number, customer, amount, method, payment status, and date. Filters support payment status and method. No digital-payment transactions were added.
StaffActivity is read-only, showing staff, action, description, reference, and timestamp; staff/action/inclusive date filters are available.

## Validation

- `manage.py makemigrations --check --dry-run`: No changes detected.
- `manage.py check`: No issues.
- `manage.py test`: 179 tests passed (144 existing + 35 new owner tests).
- `git diff --check`: passed.
- No migrations required or applied.

## Manual verification

A scripted Django test-client walkthrough against the existing database exercised the actual login form with next=/owner/, dashboard, reports, catalogue sections, inventory, staff, customers, orders, payments, and activity. All pages returned 200 after successful login. A temporary inventory adjustment was checked for the stock change, InventoryTransaction, and StaffActivity.
All writes, including temporary login credentials and sessions, were inside a database transaction that was rolled back. Existing sample data and passwords were preserved. Staff creation and all mutation/security paths were verified in the isolated test database.
This was an HTTP/application walkthrough, not a visual browser inspection. Visual desktop/mobile review remains outstanding.

## Remaining work

Visual browser review before the college defense. Optional customer-detail page and future pagination can be added later. Real digital payments, email notifications, delivery API, production deployment, and advanced accounting were intentionally deferred as requested.
