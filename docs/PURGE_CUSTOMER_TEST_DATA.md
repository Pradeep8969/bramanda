# Customer test-data cleanup

By default, this command selects **all** users whose role is CUSTOMER and whose `is_staff`
and `is_superuser` flags are both false. It does not distinguish test accounts
from real customers; use it on a test/development database.

Preview only (the default; no writes):

```powershell
.\venv\Scripts\python.exe manage.py purge_customer_test_data
```

Explicit cleanup:

```powershell
.\venv\Scripts\python.exe manage.py purge_customer_test_data --confirm
```

## Explicit five-order cleanup

`--purge-test-orders` is a separate mode: it preserves **all users and carts**,
including CUSTOMER accounts, and targets only these exact test order numbers,
even when they belong to the OWNER:

- `BRM-20261007-B6FEE3C4F7A84F8D`
- `BRM-20261007-71426BD06DB44D38`
- `BRM-20261007-4D3BE2B0FBBB4010`
- `BRM-20261007-CECD35E330FA49A1`
- `BRM-20261005-647BE3A50B274A59`

```powershell
# Preview only
.\venv\Scripts\python.exe manage.py purge_customer_test_data --purge-test-orders
# Explicit cleanup
.\venv\Scripts\python.exe manage.py purge_customer_test_data --purge-test-orders --confirm
```

This mode cannot be combined with `--include-orphaned`. Missing allowlisted
orders are reported and skipped, so repeat cleanup cannot restore stock twice.
The preview lists exact orders/items, ORDER/RETURN records to remove, net stock
restoration, related order-status/payment/delivery activity and admin logs to
remove, and protected users/carts that remain. Unrelated orders, user privilege
flags, SocialApps, catalog data, manual inventory records and activity remain
intact. Even a manual adjustment with the same reference is preserved.
All inventory reconciliation and transaction safeguards below still apply.

Add `--include-orphaned` to include orders whose customer does not exist
(including dangling non-NULL customer IDs). Orders linked to any existing
protected user are preserved regardless of this flag. Orphans are not included
by default. These options still include the ordinary CUSTOMER cleanup:

```powershell
# Preview only
.\venv\Scripts\python.exe manage.py purge_customer_test_data --include-orphaned
# Explicit cleanup
.\venv\Scripts\python.exe manage.py purge_customer_test_data --include-orphaned --confirm
```

The preview lists orphaned order numbers, item/variant quantities, matching
ORDER/RETURN inventory records, net restoration per variant, and protected
OWNER/STAFF/admin carts that remain. Orphans undergo the same reconciliation
and transactional safety checks as customer orders. The current Order schema
requires a customer; tests reproduce legacy dangling references only in the
isolated database, without schema changes.

The preview lists customers, related record counts, net stock restoration per
variant, and the protected user count. It also lists current remaining users
and order/cart/social-account/customer counts; in a dry run those are the
unchanged current database counts.

Cleanup removes the selected users, their orders/items, carts/items, allauth
SocialAccounts/SocialTokens, EmailAddresses/EmailConfirmations, user permission
assignments/group memberships, and Django admin logs authored by them or
directly referencing deleted users/orders. Order payment,
shipping, and tracking state is stored directly on Order and disappears with
it. User address/phone fields disappear with the user; there is no separate
customer profile or address model.

Inventory ORDER deductions are matched by exact order number and variant and
must reconcile with OrderItems, including repeated reservation/return cycles
from eSewa retries. RETURN records with the same order number
are subtracted from restoration. The command removes those ORDER/RETURN
records and adds only the net outstanding quantity to current stock. It
aborts on missing variants, missing/mismatched deductions, excess returns,
or an outstanding net debit greater than the ordered quantity,
including manually created orders lacking inventory history. Resolve such
inconsistencies administratively before retrying; no stock is guessed.
Cancellation status alone does not prove stock was returned. Running cleanup
again cannot restore the deleted orders a second time.

Order/payment/delivery StaffActivity entries with matching order numbers and
activity authored by removed users are deleted. Other owner/staff activity,
manual inventory adjustments, and unrelated inventory records remain. Any
remaining inventory records authored by a deleted user retain their data,
with `created_by` set to NULL through the existing model relationship.
Historical previous/new stock snapshots in preserved records remain intact.

OWNER, STAFF, staff-flagged users, and superusers survive, along with their
carts and orders outside the explicit five-order mode, catalog models/images/prices, permission definitions/groups,
SocialApp provider configuration, settings, and migrations. Confirmed cleanup
uses one transaction, checks protected users, locks affected rows, guards
stock updates against concurrent changes, and validates the user deletion
cascade. Failures roll back inventory and deletion together. Run maintenance
with application writes stopped to avoid competing checkout/signup activity.

Tests exercise confirmed cleanup only in Django's isolated test database:

```powershell
.\venv\Scripts\python.exe manage.py test accounts.test_purge_customer_test_data
```
