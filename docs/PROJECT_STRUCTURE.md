# Project structure

BRAMANDA uses multiple Django apps within one project. `manage.py` is the command-line entry point. Shared templates and static assets live at the repository root.

| Directory | Responsibility and important files |
| --- | --- |
| `accounts/` | Custom `User` model extending `AbstractUser`; CUSTOMER/STAFF/OWNER roles, phone and address. Forms and views implement registration, login/logout, and profile editing. Admin exposes the role field. `adapters.py` enforces CUSTOMER for new social users and customer-area allauth redirects; `test_social_auth.py` tests mocked OAuth and compatibility. |
| `products/` | Category, Product, ProductImage, Size, Color, and ProductVariant models. Storefront views implement search/filter/sort and product detail. ModelForms support owner catalog editing. `management/commands/seed_bramanda.py` provides sample catalog data. |
| `cart/` | One reusable Cart per user, CartItem per selected variant, quantity validation, add/update/remove views, computed totals, and navigation counter context processor. |
| `orders/` | Order and OrderItem snapshots, CheckoutForm, atomic checkout service, order confirmation/history/detail, and tracking steps. |
| `inventory/` | InventoryTransaction model and atomic `adjust_stock` service. `stock_levels.py` defines low stock as 1–5 and zero as out of stock. `views.py` is a scaffold; inventory pages are implemented in dashboard. |
| `dashboard/` | Staff operations in `views.py`, owner metrics/catalog/reports/staff/payment/activity pages in `owner_views.py`, separate URL modules and forms, role decorators in `permissions.py`, and StaffActivity model. Owner operational views wrap shared staff views. |
| `payments/` | Installed app scaffold. No custom model, implemented view, URL module, or substantive test exists. Payment method/status belong to Order; payment handling pages are in dashboard. |
| `bramanda/` | Project settings, root URLs, home view, WSGI and ASGI entry points. It is the project configuration package, not a separate business-data app. |
| `templates/` | Shared base/home and account, storefront, cart, order, staff dashboard, and owner templates. |
| `static/` | Local CSS, JavaScript, and assets, including storefront/product and dashboard interaction code. |
| `media/` | Uploaded product and gallery images; file paths are stored by ImageField. |
| `scripts/` | Customer, order, and staff test-client walkthrough scripts that roll back verification writes. These are not browser automation. |
| `docs/` | Architecture, database, workflows, installation, and testing documentation. |
| `venv/` | Local Python environment; not application source or a dependency declaration. |

## Common app files

`models.py` defines database entities; `forms.py` validates input; `views.py` handles HTTP requests; `urls.py` selects views; `admin.py` registers administrative interfaces; and `apps.py` declares the app. Business services appear where needed in orders and inventory rather than in every app. Committed `migrations/` represent schema history.

Tests are stored in `tests.py` and additional `test_*.py` modules. The root `OWNER_DASHBOARD_REPORT.md` is an earlier implementation/verification report and is distinct from the current test results in [Testing](TESTING.md).
