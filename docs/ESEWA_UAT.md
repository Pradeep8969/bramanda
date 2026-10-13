# BRAMANDA eSewa UAT payments

## Root cause

The original configuration copied the status endpoint from the older Epay-V2 documentation: `https://uat.esewa.com.np/api/epay/transaction/status/`. A real read-only probe failed before HTTP with Windows DNS error 11001. The form host, documentation host and a control host resolved, so this was specific to the configured verification hostname. Requests raised ConnectionError, and the application collapsed DNS, TLS, timeout, HTTP and JSON failures into one generic error.

The current official ePay documentation, which still specifies the same V2 form and callback signing protocol, lists `https://rc.esewa.com.np/api/epay/transaction/status/`. A read-only request there returned HTTP 200, JSON, and COMPLETE for the existing pending sandbox attempt, with its stored transaction UUID, merchant and amount matching. The default now uses that endpoint. The older documented endpoint remains an explicit allowed override, but should not be used on this machine while DNS fails. No undocumented endpoint fallback or security bypass is used.

The callback also always redirected to the payment result page, even after verified success. It now redirects to the exact order's details only after verified COMPLETE and safe reconciliation. Manual verification does the same. Exceptional paid orders requiring staff review remain on the payment result page. The order details display verified payment information and expose the paid receipt. Fulfillment and delivery remain staff-controlled.

## Verification and safety

- The form and status request use the stored UUID, merchant snapshot and Decimal amount. Browser amounts/statuses are ignored.
- A supplied Base64 success response must have the documented signed fields, HMAC-SHA256 signature and exact identity/amount. Callback and API references must agree. Without a callback payload, only the independent API result can authorize payment.
- COMPLETE requires a transaction reference. Pending, ambiguous, unknown, unreadable and unavailable responses never authorize payment. Verified NOT_FOUND/failure/cancellation releases inventory once.
- A conditional database write claims a 60-second verification lease, including on SQLite. Overlapping checks return HTTP 409. An expired worker cannot overwrite a newer check. Network I/O happens outside the stock transaction.
- Reconciliation locks the order/payment and uses existing conditional inventory writes. Duplicate callbacks/checks never create orders or attempts, never deduct stock twice, and never regress paid attempts to pending/failed.
- Retry creates a new UUID only for eligible failed/cancelled orders and preserves old attempts. Late payments and extra paid attempts are recorded for staff review.
- Refund references must match the original payment where recorded. Full refunds revoke paid receipt access. Partial refunds and exceptional payments require staff review; refunds do not automatically return stock.
- Manual verification requires login, authorization, POST and CSRF. Existing staff reconciliation access is preserved. Provider callbacks can verify without a session; customer order details still require login/ownership.
- Status requests use a fixed official UAT URL, disable redirects and use a 10-second connect/read timeout. Merchant secrets and raw provider errors are never sent to the browser or logged.
- Last attempted check and last successful verification are separate timestamps. Failed checks retain the last successful time. Safe diagnostic codes distinguish DNS, TLS/proxy/network, connect/read timeout, HTTP authorization/not-found/redirect/error, invalid JSON, provider unavailable/rejected, malformed data, identity/amount/reference mismatch and unknown status.
- Check history stores only error codes, safe messages, HTTP status, response format, elapsed milliseconds and verified references. Logs contain an internal payment ID and safe diagnostic metadata, never raw response/exception text or sensitive transaction details. History is read-only in Django admin.

## PowerShell commands

Start the local app:

```powershell
Set-Location 'C:\Users\prade\Documents\bramanda'
$env:ESEWA_ENV = 'uat'
$env:ESEWA_PRODUCT_CODE = 'EPAYTEST'
$env:ESEWA_PAYMENT_URL = 'https://rc-epay.esewa.com.np/api/epay/main/v2/form'
$env:ESEWA_STATUS_URL = 'https://rc.esewa.com.np/api/epay/transaction/status/'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:8000'
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The project defaults to the published UAT signing key. If ESEWA_SECRET_KEY is already overridden in your environment, configure the published UAT value from the official documentation locally. Never use a production key with UAT.

Run checks in a second PowerShell window:

```powershell
Set-Location 'C:\Users\prade\Documents\bramanda'
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py showmigrations payments
.\venv\Scripts\python.exe manage.py migrate --check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\venv\Scripts\python.exe manage.py test payments orders --noinput
.\venv\Scripts\python.exe manage.py test --noinput
node --check .\static\js\payment-result.js
node --test .\scripts\test_payment_result.cjs
```

Read-only diagnostics (makes one status request, never updates orders, payments or inventory):

```powershell
.\venv\Scripts\python.exe manage.py diagnose_esewa
# If no pending attempt remains, specify an internal payment ID from Django admin:
.\venv\Scripts\python.exe manage.py diagnose_esewa --payment-id 1
```

Restart Django after changing the environment. Existing process variables take precedence over `.env`. If an old PowerShell session still sets ESEWA_STATUS_URL to the uat hostname, explicitly set the rc endpoint as above before starting the server.

Payment tests mock outbound eSewa traffic and use a separate test database. The JavaScript tests execute the actual page script against a mocked DOM and fetch implementation. They test POST/CSRF, loading, duplicate suppression, success/pending/canceled/error feedback, retry, login expiry and timeout handling.

## Complete UAT walkthrough

1. Open http://127.0.0.1:8000 on the computer running Django and sign in as a customer.
2. Add an in-stock product, choose eSewa at checkout, and confirm subtotal + NPR 100 delivery. For the reported example, NPR 4,225 + 100 = 4,325.
3. Continue to eSewa and confirm merchant EPAYTEST and the total. The current ePay documentation lists sandbox wallet IDs 9711111111, 9711111112, 9711111113 and 9711111114, password Nepal@123, token 123456. The older V2 page lists 9806800001 to 9806800005; use a currently available UAT wallet, never a real wallet.
4. Complete the final eSewa confirmation and allow the browser to return. The server validates the signed callback and independently verifies the original UUID. Only matched COMPLETE marks payment/order PAID and moves a normal pending order to CONFIRMED. Delivery remains PENDING. You are redirected automatically to the matching order details with verified payment confirmation and a paid receipt link.
5. Click Verify Payment. The spinner and Checking payment… appear, the button disables, then status/reference/time update or a helpful retryable error appears. Repeating checks must preserve the payment UUID, order and stock reservation.
6. Test cancellation separately. The failure redirect is not trusted; only a verified terminal failure exposes a fresh-attempt retry. Pending/ambiguous results remain unresolved.
7. Check the order in the owner/staff dashboard. Unpaid orders cannot be treated as paid. Exceptional late payments/refunds require staff review.
8. Check desktop and mobile layouts and keyboard navigation in a real browser. Without JavaScript, the POST form still verifies and displays a Django message after redirect.

Current official V2 protocol, status endpoint, response fields and sandbox credentials: https://developer.esewa.com.np/pages/Epay

Older V2 page (different status hostname and test wallet list): https://developer.esewa.com.np/pages/Epay-V2

## Limitations

No payment or charge was initiated during implementation. Live read-only UAT status checks independently confirmed COMPLETE for an existing sandbox transaction. Mocked tests validate the application and redirect behavior; a new end-to-end browser checkout still requires the walkthrough above.

After the full regression suite passed, the existing attempt was rechecked through the corrected verifier and reconciled: payment PAID, order payment PAID, order CONFIRMED, delivery PENDING, verified reference/time recorded. The original UUID, order/payment counts, stock and inventory-record count were unchanged. The owning customer's paid receipt view returned HTTP 200. This reconciliation used provider-backed verification, not a fabricated callback or manually assigned paid status.

Localhost redirects work only on the same computer while Django is running. eSewa cannot deliver server-to-server notifications to localhost; a mobile device resolves localhost on that device. This integration uses browser callbacks/manual status checks, not a new IPN endpoint. Outbound HTTPS access to UAT is still required.

Use the same hostname throughout to preserve cookies. Lost sessions require login to view order details even if the callback already verified payment. External-device/IPN testing needs a public HTTPS origin and matching Django host/CSRF configuration.

Automatic polling is omitted. UAT availability and propagation delays are controlled by eSewa. Under SQLite writer contention, reconciliation rolls back and asks for a retry. Responsive CSS, templates and script behavior are checked, but actual browser viewport rendering and visual accessibility still need the walkthrough above.
