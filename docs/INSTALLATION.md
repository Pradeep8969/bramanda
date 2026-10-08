# Windows / PowerShell installation

Run commands from the project root unless stated otherwise. This guide follows the repository's actual Git remote, settings, custom user model, and `seed_bramanda` command.

## 1. Clone the project

Have Git and Python available in PowerShell. The inspected environment uses Python 3.14.8; no supported-version range is declared in the repository.

```powershell
git clone https://github.com/Pradeep8969/bramanda.git
cd bramanda
```

## 2. Create and activate a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If local policy prevents activation, use `.\venv\Scripts\python.exe` in place of `python` in the remaining commands. Activation is a convenience, not a requirement, and this alternative requires no execution-policy change.

## 3. Install dependencies

The repository now provides `requirements.txt` for its direct runtime dependencies:

```powershell
python -m pip install -r requirements.txt
```

This installs Django 6.1.1, Pillow 12.3.0, and django-allauth 65.19.7 with its socialaccount dependencies. These versions are observed locally. The allauth installation succeeded in the existing virtual environment; a complete clean-clone installation has not been tested.

## 4. Apply existing migrations

```powershell
python manage.py migrate
```

Django uses `db.sqlite3` at the repository root. This command applies committed BRAMANDA migrations, Django's built-in migrations, and packaged allauth account/socialaccount migrations. Do not generate new migrations merely to install the project. Uploaded images are stored under `media/`, outside the database.

## 5. Load optional sample catalog

```powershell
python manage.py seed_bramanda
```

The command creates the T-Shirts category, sizes S/M/L/XL, colors Black/Beige/Bottle Green, and Bramanda Oversized T-Shirt priced at Rs. 845.00. Twelve variants receive initial stock through `adjust_stock`, producing STOCK_IN history. Repeated runs preserve existing product/variant data and stock; newly created variants are seeded. It creates no users, orders, or sample credentials, and supplies no product images.

## 6. Create an administrator and assign the owner role

```powershell
python manage.py createsuperuser
```

Enter your own credentials; no default password is verified or supplied. Because `User.role` defaults to CUSTOMER, creating a superuser alone does not grant `/owner/` access.

After starting the server, sign in to `/admin/`, open the user record, set **role = Owner**, and save. Django admin exposes this field through `BramandaUserAdmin`. The owner can then create STAFF accounts through `/owner/staff/add/`. Public registration always creates CUSTOMER accounts. `is_staff` controls Django admin access separately from the application's STAFF role.

## 7. Start the application

```powershell
python manage.py runserver
```

Visit `http://127.0.0.1:8000/`, `/shop/`, `/owner/`, or `/staff/` as appropriate. Login normally redirects to the storefront; open the relevant dashboard directly after login. Settings use SQLite, UTC, local static/media directories, and DEBUG enabled. Email uses environment-configured SMTP; before development signup, set `$env:EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'` or configure real SMTP credentials. See [Email and password reset](EMAIL_AND_PASSWORD_RESET.md).

For Google/Facebook sign in, follow [Social login setup](SOCIAL_LOGIN.md) to create provider projects and enter credentials in Django admin SocialApp records. Sites/SITE_ID and Site associations are not required. Password login works before social credentials are configured.

## 8. Verify the checkout

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Tests use an isolated test database. The dry-run checks model/migration consistency without creating migration files. See [Testing](TESTING.md).
