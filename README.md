# BRAMANDA – THE UNDISCOVERED

**Business & E-Commerce Management System for a clothing/fashion brand**

## Project overview

BRAMANDA combines a customer storefront with staff operations and owner management in one Django application. Customers purchase size/color variants using Cash on Delivery (COD), staff manage fulfillment and stock, and owners manage the catalog, staff, reports, and payment overview. Pages are rendered with Django templates and local HTML, CSS, and JavaScript.

## Problem statement

A clothing brand must track stock separately for each size/color combination while keeping customer purchases, delivery progress, and business records consistent. Separate manual records can lead to stock errors and make order follow-up difficult. This project centralizes those records and gives each role access to its relevant tasks.

## Objectives

- Provide a searchable storefront and secure customer accounts.
- Maintain SKU-level inventory and a history of stock changes.
- Convert validated carts into orders with reliable financial and product snapshots.
- Support order processing, customer tracking, and COD collection recording.
- Give owners management tools and database-based business reports.
- Enforce access rules on the server and verify behavior with automated tests.

## Main features

- Registration, username/password login, POST logout, and profile editing.
- Google/Facebook customer signup and login through django-allauth, with POST/CSRF initiation and admin-configured credentials.
- Product search, category/size/color filtering, sorting, images, and gallery display.
- Product variants with unique SKU, size, color, active status, and stock quantity.
- Account-based cart with quantity updates, removal, and stock validation.
- COD checkout, fixed shipping charge of Rs. 100.00, order confirmation, history, and status tracking.
- Atomic order creation, stock deductions, inventory history, and cart clearing.
- Staff order search and status updates, delivery updates, COD paid action, inventory adjustments, and read-only customer information.
- Owner catalog and staff management, inventory, orders, customers, payment overview, activity log, dashboard metrics, and date-filtered reports.
- Responsive layouts in CSS and Django automated tests. Visual browser verification is separate from HTTP tests.

## User roles

| Role | Main access |
| --- | --- |
| Customer | Public storefront, own profile/cart/orders, checkout and tracking |
| Staff | Staff dashboard, all operational orders, delivery/payment updates, active-variant inventory adjustments, customer list |
| Owner | Owner dashboard, reports, catalog, staff management, payments and activity; also staff operations |

Public registration always creates a CUSTOMER. Django admin access uses Django's own privilege flags; application dashboards check the `role` field separately.

## Technology stack

Python, Django, SQLite, Django ORM/forms/templates/authentication, HTML, CSS, JavaScript, Pillow for image fields, and django-allauth for Google/Facebook customer sign in. The inspected environment uses Python 3.14.8, Django 6.1.1, Pillow 12.3.0, and django-allauth 65.19.7. `requirements.txt` pins direct runtime dependencies; the socialaccount extra supplies transitive OAuth dependencies.

## Project structure

```text
bramanda/
├── manage.py
├── bramanda/       # Project configuration and home page
├── accounts/       # Custom user and account forms/views
├── products/       # Catalog, storefront, sample-data command
├── cart/           # Account cart and cart items
├── orders/         # Checkout, snapshots, order history
├── inventory/      # Stock service and transaction ledger
├── dashboard/      # Staff/owner pages, access guards, activity
├── payments/       # Installed scaffold; payments live on Order
├── templates/      # Shared and area-specific templates
├── static/         # CSS, JavaScript, and static assets
├── media/          # Uploaded images
├── scripts/        # Test-client walkthroughs
└── docs/           # College-project documentation
```

See [Project structure](docs/PROJECT_STRUCTURE.md) and [System architecture](docs/SYSTEM_ARCHITECTURE.md).

## Installation and running

Install runtime dependencies from `requirements.txt`. Existing account and sample-data workflows remain available alongside social authentication.

```powershell
git clone https://github.com/Pradeep8969/bramanda.git
cd bramanda
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_bramanda
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Sample data is optional and creates one oversized T-shirt with 12 variants. It does not create login accounts. A superuser defaults to CUSTOMER unless its role is explicitly changed; use `/admin/` to set the intended owner's role to OWNER. See [Installation](docs/INSTALLATION.md) for activation alternatives and role setup.

Configure Google/Facebook credentials through admin SocialApp records using [Social login setup](docs/SOCIAL_LOGIN.md). No Sites/SITE_ID is required by this installed allauth configuration. Without credentials, social buttons are disabled and password forms remain available.

## Tests and checks

From the repository root, using the existing Windows environment:

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

See [Testing](docs/TESTING.md) for coverage and verification results.

## Main URL routes

| Route | Purpose |
| --- | --- |
| `/` | Brand home page |
| `/register/`, `/login/`, `/logout/`, `/profile/` | Accounts; logout requires POST |
| `/accounts/` | django-allauth routes, including Google/Facebook OAuth callbacks and account connections |
| `/shop/`, `/shop/<slug>/` | Product list and detail |
| `/cart/` | Current user's cart |
| `/cart/add/<slug>/`, `/cart/update/<item_id>/`, `/cart/remove/<item_id>/` | POST cart operations |
| `/checkout/` | Checkout form and order submission |
| `/orders/`, `/orders/<order_number>/`, `/orders/<order_number>/success/` | Own order history, detail/tracking, confirmation |
| `/staff/` | Staff dashboard |
| `/staff/orders/`, `/staff/orders/<order_number>/` | Operational orders |
| `/staff/customers/`, `/staff/inventory/` | Customer information and inventory |
| `/owner/`, `/owner/reports/` | Owner metrics and reports |
| `/owner/products/`, `/owner/categories/`, `/owner/sizes/`, `/owner/colors/`, `/owner/variants/` | Catalog management |
| `/owner/orders/`, `/owner/customers/`, `/owner/inventory/` | Owner operational areas |
| `/owner/staff/`, `/owner/payments/`, `/owner/activity/` | Staff, order-based payment overview, activity |
| `/admin/` | Django administration |

Catalog sections support `add/`, `<pk>/edit/`, and POST `<pk>/toggle/`. Owner staff management follows the same suffix pattern. Both operational areas have POST `inventory/adjust/` and order-detail suffixes `status/`, `delivery/`, and `payment/`. There is no separate `/payments/` application route.

## Default workflow

Register/login → browse → choose size/color variant → cart → checkout → confirmed COD order → stock deduction and cart clearing → view tracking. Staff update fulfillment and record payment collection. Owners review results and manage the business. See [Workflow](docs/WORKFLOW.md).

## Security and RBAC

Django handles password hashing, password validation, sessions, authentication, and CSRF middleware. Registration and profile forms restrict editable fields. Customers can access only their own cart and order pages. `staff_required` requires an active STAFF or OWNER; `owner_required` requires an active OWNER. Superuser flags do not bypass these guards. Mutations use POST and forms validate submitted values. Server-side prices, stock, and totals override untrusted client values. Checkout and stock history use database transactions; the inventory service includes a conditional stock update because SQLite does not provide row locking.

The checked-in settings are for development: DEBUG is enabled, the secret key is in settings, and allowed hosts are empty. Production configuration is future deployment work.

## Screenshots

Screenshots have not been captured for this documentation. Add verified images before submission.

| Suggested screenshot | Placeholder |
| --- | --- |
| Home and storefront | To be added |
| Product size/color selection | To be added |
| Cart and COD checkout | To be added |
| Order confirmation and tracking | To be added |
| Staff orders and inventory | To be added |
| Owner dashboard and reports | To be added |
| Mobile storefront and dashboard | To be added |

## Future improvements

Possible extensions include a complete transitive dependency lock, production configuration, digital payment integration, customer notifications, delivery-provider integration, pagination, advanced accounting, and automated visual/browser tests. These are proposed improvements, not implemented features.

## Documentation

- [ER diagram](docs/ER_DIAGRAM.md)
- [Database design](docs/DATABASE.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md)
- [Workflow](docs/WORKFLOW.md)
- [Testing](docs/TESTING.md)
- [Windows installation](docs/INSTALLATION.md)
- [Project structure](docs/PROJECT_STRUCTURE.md)
- [Google/Facebook social login](docs/SOCIAL_LOGIN.md)
