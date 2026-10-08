# BRAMANDA payments: COD and eSewa ePay V2 UAT

This college-project integration is **TEST/UAT only**. It does not support live
merchant configuration or store wallet passwords, MPINs, login credentials,
access tokens, or callback bodies. Wallet credentials are entered only on
eSewa's own test page. The public UAT signing key is not a production secret.

Official references, reviewed on 2026-10-08:

- [eSewa ePay V2 integration, signatures and status verification](https://developer.esewa.com.np/pages/Epay-V2)
- [eSewa test credentials](https://developer.esewa.com.np/pages/Test-credentials)
- [RFC 4231 HMAC-SHA256 test vectors](https://www.rfc-editor.org/info/rfc4231/)

## Order and payment state

Order status continues to describe fulfillment. Payment status separately uses
UNPAID, PENDING, PAID, FAILED, CANCELLED, and REFUNDED. Order retains its payment
method/status for the existing portals; payment services synchronize it with
Payment records. Payment stores order, method, status, amount, unique UUID,
transaction code/provider reference, paid timestamp, creation/update times,
and a staff-review flag. Retry history is retained. A database constraint
permits only one pending attempt per order.

COD checkout creates a CONFIRMED order, deducts stock through the existing
checkout service, and records an UNPAID COD Payment. The order confirmation
and invoice show Amount Due. They do not invent a provider transaction number
or claim payment has been received. Authorized active STAFF/OWNER accounts
use the existing payment-received button to collect COD. Collection records
PAID and paid_at, and enables a printable receipt. Repeated collection is
idempotent. Customers cannot use these management actions.

eSewa checkout creates an order and attempt with payment PENDING and
fulfillment PENDING. Stock deduction and attempt creation are one transaction.
The customer continues to the official UAT form from a BRAMANDA payment page.
Staff cannot mark eSewa paid using the COD control or progress unpaid eSewa
fulfillment/delivery. Django admin displays payment status read-only; use
verified payment services and the existing portal controls.

## Configuration

Environment variables are read from the process environment; `.env` files are
not automatically loaded. Restart Django after changing them.

| Variable | UAT default |
| --- | --- |
| `ESEWA_ENV` | `test` (`uat` also accepted) |
| `ESEWA_PRODUCT_CODE` | `EPAYTEST` |
| `ESEWA_SECRET_KEY` | Published public UAT key from the official documentation |
| `ESEWA_PAYMENT_URL` | `https://rc-epay.esewa.com.np/api/epay/main/v2/form` |
| `ESEWA_STATUS_URL` | `https://uat.esewa.com.np/api/epay/transaction/status/` |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000` |

This build rejects production environment values, merchant codes and endpoint
URLs. Do not put live credentials in these settings. An empty signing key
rejects eSewa checkout and rolls back the order/cart/stock transaction.

Example PowerShell session:

```powershell
$env:ESEWA_ENV = 'test'
$env:ESEWA_PRODUCT_CODE = 'EPAYTEST'
$env:ESEWA_PAYMENT_URL = 'https://rc-epay.esewa.com.np/api/epay/main/v2/form'
$env:ESEWA_STATUS_URL = 'https://uat.esewa.com.np/api/epay/transaction/status/'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:8000'
# Optional override: copy ONLY the public UAT Secret Key from the official page.
# The published UAT key is already the test-only default.
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

Use the same hostname when browsing so the logged-in session is available on
return. If testing through a public HTTPS tunnel, configure its origin in
PUBLIC_BASE_URL and the corresponding ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS.
BRAMANDA ignores the incoming Host header when building payment return URLs.

## Amounts and signatures

All amounts come from Order snapshots created using current database prices.
The browser cannot supply the amount payable. The existing delivery charge
is Rs.100: amount is order.subtotal, product_delivery_charge is
order.shipping_cost, and total_amount is order.grand_total. Tax and service
charges are zero. The delivery fee is therefore counted exactly once.

The request signing string is assembled in this exact order:

```text
total_amount=<two-decimal total>,transaction_uuid=<unique UUID>,product_code=EPAYTEST
```

HMAC-SHA256 uses the configured UAT key; the raw digest is Base64 encoded.
`signed_field_names` is `total_amount,transaction_uuid,product_code`.
Request/response signature comparison uses constant-time comparison.
Tests independently verify the algorithm against RFC 4231 and check the
actual order/form signing string; do not copy a static example signature.

## Callback and status verification

Success callbacks decode the size-limited Base64 JSON data and reject malformed
JSON, duplicate keys, unexpected signed-field lists, invalid signatures,
wrong UUID/product code, altered amount, missing transaction code, and any
callback status other than COMPLETE. The required response signing order is:

```text
transaction_code,status,total_amount,transaction_uuid,product_code,signed_field_names
```

After signature validation, BRAMANDA calls the fixed UAT status endpoint with
its stored attempt UUID, stored amount and configured product code. The
response must match all three. Both official response naming conventions
(`pid/scd/totalAmount/refId` and `transaction_uuid/product_code/total_amount/ref_id`)
are supported. A successful callback's code must also match the API reference.

Only authoritative COMPLETE with a matching reference sets PAID, records
reference and paid_at, and normally moves fulfillment from PENDING to
CONFIRMED. The success URL alone is insufficient. Failure redirects are
unsigned: they trigger the same server status check, never trust a query-string
status. Customer/staff re-checks require authenticated, authorized CSRF-protected
POSTs. Provider redirects use GET as required by ePay; they do not require
a session to validate a payment. Viewing documents/results still requires
authentication and ownership or the existing active STAFF/OWNER role.

PENDING, ambiguous/unknown responses, network failures, timeouts, redirects
from the verification endpoint, and unavailable/error responses do not become
paid and do not release stock. FAILED/NOT_FOUND map to FAILED;
CANCELED/CANCELLED map to CANCELLED. A verified full refund changes a paid
attempt to REFUNDED, without automatically treating merchandise as returned.
Partial refunds require merchant/staff review; no refund-issuance API is built.

## Inventory and retries

Approach B is used: create the order with the existing stock deduction, then
restore/cancel on a definitively verified failure. OrderItems must match the
net ORDER/RETURN inventory ledger by exact order number and variant. Missing
variants/history or mismatches abort reconciliation transactionally.

Failure/cancellation writes RETURN records and marks payment_stock_released
exactly once. The order becomes CANCELLED. A retry requires that release flag,
a failed/cancelled payment, no active/paid attempt, sufficient current stock,
and still-active catalog variants. It re-reserves stock atomically with new
ORDER records and creates a fresh UUID/PENDING attempt. Pending attempts are
continued or re-checked rather than replaced. Duplicate callbacks, old failed
callbacks, and duplicate retries cannot deduct or return stock twice.

Customers can close the provider page without returning. Run this command
periodically (for example every minute through a scheduler) to resolve pending
attempts based on UAT state:

```powershell
.\venv\Scripts\python.exe manage.py reconcile_esewa_payments
```

This command contacts UAT and can change payment/order/stock state only after
verification. It is not the customer-data purge command. Ambiguous/provider
outage cases remain reserved and require follow-up; elapsed local time alone
is not proof that the provider did not receive funds. The project does not
install a background scheduler automatically.

Late authoritative success is retained even if a prior failure released stock.
It attempts to reserve the items again. If stock is now unavailable, the real
payment is recorded PAID with review_required, the order stays CANCELLED,
and fulfillment is blocked until staff resolves stock/refund handling.
If two distinct attempts genuinely complete, both payments are recorded,
the extra payment is flagged for review, and stock is deducted only once.
Staff must resolve extra charges with the merchant; money is never silently
discarded or falsely labelled refunded. Retry forms are hidden once the
order is paid. Order-level paid revenue counts each eligible order once,
not duplicate charges. Order receipts show the first paid attempt; all
attempts/references remain visible to STAFF/OWNER.

Existing purge reconciliation also understands retry ORDER/RETURN cycles
and previews Payment attempts, but **do not use purge commands for payment
reconciliation**. No cleanup command is needed to enable payments.

## Documents, reports and migrations

Every placed order has a responsive Order Confirmation / Invoice. COD unpaid
documents show UNPAID and Amount Due, with no Amount Paid or fabricated
transaction reference. Only an order with PAID status and a PAID Payment
has a Payment Receipt, including amount, receipt number, items/totals,
payment method/date and eSewa reference where applicable. Unpaid, pending,
failed, cancelled and fully refunded orders have no paid-receipt access.
Print buttons use browser printing and print CSS.

My Orders and detail pages distinguish Order Status and Payment Status.
Retry is offered only when safe; pending eSewa has Continue/Re-check actions.
Existing staff/owner screens show amounts, paid_at, references and attempt
history. Owner payment/reports distinguish unpaid COD, pending eSewa,
failed/cancelled and refunded amounts. Existing revenue semantics remain
paid, non-cancelled orders; unpaid/failed payments are never paid revenue.

Three migrations add the Order stock-release flag/method/status choices,
create Payment, and backfill existing Order records. Historical COD PENDING
becomes UNPAID. Existing paid orders remain paid, with no invented paid_at or
eSewa reference; their receipts explicitly identify unrecorded legacy dates.
User roles, carts, prices, product stock and SocialApps are not modified by
these migrations.

## Manual UAT walkthrough

1. Apply migrations and launch Django from the configured PowerShell session.
2. Sign in as a CUSTOMER, add an in-stock item, and open checkout. Confirm the
   two payment choices and a single Rs.100 shipping charge.
3. Select COD. Confirm UNPAID, Amount Due on the invoice, no receipt, and a
   single stock deduction. As STAFF/OWNER, mark payment received; confirm
   paid_at and a printable receipt. A CUSTOMER must be denied that action.
4. Place a separate order using eSewa. Confirm payment/order PENDING and
   continue from BRAMANDA's page to the official UAT wallet form.
5. Use credentials from the official test-credentials page linked above.
   Its wallet credentials currently differ from those listed in the ePay V2
   page's credentials section; use the current page/provider guidance for
   your UAT environment. Never use a personal/live wallet. BRAMANDA does
   not collect or save those credentials.
6. Complete the UAT payment. Verify return to Payment successful, stored
   transaction reference/paid_at, order CONFIRMED and the printable receipt.
   Refresh the callback; stock and receipt data must not duplicate.
7. Place another eSewa order and cancel at the provider. Re-check its status
   if it returns pending. Only verified cancellation/failure releases stock;
   then Retry must create a new attempt and reserve the items once.
8. Close a pending provider page without returning; run reconciliation or
   use Re-check. A provider outage must retain PENDING and no paid receipt.
9. Inspect staff/owner payment history and revenue categories. Confirm no
   unpaid/failed order contributes to paid revenue. Manually opening a
   success URL without signed response data must not mark payment paid.

Automated tests use an HTTP network guard and mock eSewa status calls;
they do not contact real eSewa. Browser/provider UAT transactions and actual
receipt print rendering require this manual review; they are not claimed
as automatically verified.

## Work required before production

Complete eSewa merchant onboarding and UAT acceptance. A reviewed production
deployment must explicitly extend the current test-only configuration guard,
replace EPAYTEST/public UAT key and both UAT endpoints with approved merchant
values, and use a deployment secret manager without committing credentials.
Changing environment variables alone intentionally cannot enable production.

Also configure HTTPS/trusted callback origins, production Django security,
scheduled reconciliation with monitoring, callback/request abuse controls,
provider-confirmed settlement/refund workflows, staff reconciliation for
late/duplicate payments, database concurrency/load validation, backups, and
receipt/accounting requirements. Google/Facebook/password authentication and
existing role permissions are unchanged by this integration.
