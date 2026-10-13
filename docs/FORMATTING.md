# Project formatting

This setup formats source code without redesigning pages or refactoring business
logic. Migrations, virtual environments, dependencies, generated artifacts,
uploads, collected static files, databases, and environment files are excluded.

Install the development tools:

```powershell
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm install --ignore-scripts
```

Run the formatters:

```powershell
venv\Scripts\python.exe -m ruff check . --select I --fix
venv\Scripts\python.exe -m black .
venv\Scripts\python.exe -m djlint templates --reformat
npm run format:assets
```

Black owns Python formatting; Ruff organizes imports. Ruff reports F401/F811 but
does not automatically remove unused imports or declarations. Importing a module
can have side effects, so review those warnings individually. Existing warnings
are in `cart/admin.py`, `inventory/views.py`, `orders/emails.py`, and
`payments/test_invoice_links.py`; they were retained during this formatting pass.

djLint uses the Django profile. Inline JavaScript/CSS and attribute template
expressions are not reformatted as separate languages. `<br>` stays inline, and
two guarded regions in `templates/home.html` and `templates/payments/result.html`
preserve exact markup asserted by existing regression tests. Do not remove the
`djlint:off/on` comments without checking those tests. Some long inline fragments
are intentionally retained by djLint to preserve text/element relationships.
Do not use Prettier on Django HTML.

Install the recommended VS Code extensions. Python, CSS, and JavaScript format
on save. Python save actions organize imports without running Ruff fix-all.
Django HTML uses djLint via **Format Document**, with save formatting disabled so
whitespace-sensitive template changes can be reviewed explicitly. Tools honor
project exclusions; generated files should not be formatted manually.

Check formatting and functionality:

```powershell
venv\Scripts\python.exe -m black . --check
venv\Scripts\python.exe -m ruff check . --select I
venv\Scripts\python.exe -m djlint templates --check
npm run check:assets
venv\Scripts\python.exe manage.py check
venv\Scripts\python.exe manage.py test --noinput
node --test products/tests_js/*.js products/tests_js/*.cjs scripts/test_inventory.cjs scripts/test_messages.cjs scripts/test_payment_result.cjs
```

The initial formatting audit is in `artifacts/formatting-audit`: source snapshots,
the starting Git status, per-file diffs, counts, template compilation results,
Python AST comparison ignoring import order, and JavaScript/CSS comparisons.
These generated audit files are excluded from bulk formatting. Baseline and final
Django test logs are `formatting-baseline.log` and `formatting-after.log`.
