# Backend order confirmations

Settings already load `.env` beside `manage.py`, preserving existing process variables.
All four EMAILJS values stay in backend settings. SMTP welcome/allauth mail is unchanged.
The API is https://api.emailjs.com/api/v1.0/email/send with the private key in `accessToken`.
No credentials, provider responses, exception bodies or customer details are logged.

## Template setup

For a stored `FAILED / HTTP_403`, the request reached the provider and was
rejected. The historical response body is not retained; do not infer the exact
reason from the status alone. Check Account → Security for non-browser API access
and private-key authorization, and verify the backend credentials belong to that
account. New recognized non-browser rejection responses record
`SERVER_API_DISABLED` without storing provider text.

After repairing account configuration, check EmailJS history for the specific
order and attempt time. Only if it was not accepted, run:
`venv\Scripts\python.exe manage.py retry_order_confirmation --order-id 29 --confirmed-not-accepted`
(Replace 29 with the intended order ID.) This explicitly retries only one stored
403 rejection. It refuses SENT, SENDING, UNKNOWN and other failure codes, and
retains the existing atomic claim. The pending batch command never retries FAILED
records. No automatic historical backfill is performed.

Enable non-browser API access in EmailJS Account → Security, and private key authorization.
Set the order template's recipient to `{{to_email}}` (or map its existing recipient variable).
Canonical variables are defined in `orders/emails.py`: `customer_name`, `to_email`,
`order_number`, `order_date`, `products`, `items` (structured list), `products_html`,
`subtotal`, `shipping_cost`, `grand_total`, `currency`, `payment_method`,
`payment_status`, `amount_paid`, `amount_due`, `transaction_code`, `payment_reference`,
`paid_at`, `shipping_address`, `delivery_address`, `phone_number`, and `invoice_url`.
Several common name/email/total aliases are included.
For existing names, set `EMAILJS_TEMPLATE_VARIABLES` in Django settings, mapping
template names to canonical names, e.g. `{'recipient': 'to_email'}`.
The configured cloud template cannot be inspected using the four send credentials;
its exact names must be supplied by the account owner. Do not assume aliases guarantee a match.
Use escaped double-brace variables for customer data. `products_html` is HTML-escaped
on the backend and may use triple braces; `products` is plain text.

## Localhost test

### Shipping and product table variables

Use `Rs. {{shipping}}` for shipping (the existing `shipping_cost` alias also
works), `Rs. {{subtotal}}` for subtotal, and `Rs. {{grand_total}}` for the
grand total. These are two-decimal strings from the saved order, without a
currency prefix. No shipping fee or total is hardcoded in the email payload.

EmailJS supports list-of-object section loops. Keep the existing
`{{#orders}}...{{/orders}}` loop and use the following row fields in the
template's HTML editor, inside the product table:

```html
<tbody>
{{#orders}}
<tr>
  <td>{{name}}</td>
  <td>{{units}}</td>
  <td>Rs. {{price}}</td>
  <td>Rs. {{total}}</td>
</tr>
{{/orders}}
</tbody>
```

Each `orders` entry contains the purchased name, integer quantity (`units`),
saved unit price (`price`) and saved line subtotal (`total`). Use double braces
to escape product names. The original `items`, `products`, and `products_html`
parameters remain available. No loop replacement or raw HTML variable is needed.
If the template currently uses `cost.shipping`, change it to `shipping` (the
backend provides top-level totals, not a `cost` object). Keep payment and
`invoice_url` variables unchanged. Updating the backend does not resend SENT
confirmations; validate with a new eligible order.

Loop syntax reference: https://www.emailjs.com/docs/user-guide/dynamic-variables-templates/

1. Run `venv\Scripts\python.exe manage.py migrate`, then
   `venv\Scripts\python.exe manage.py runserver`.
2. Sign in at http://127.0.0.1:8000, add an in-stock product, and check out with
   an email address you control. Select COD. After successful creation, check
   your inbox/spam and EmailJS history. The email uses checkout snapshots,
   including the delivery address, products, prices and shipping fee.
3. Repeat with eSewa TEST/UAT. No email is sent during pending checkout.
   Finish payment and allow the backend to verify COMPLETE with the provider.
   Failed, pending, invalid, refunded or financial-review payments do not confirm.
4. Click **VIEW YOUR INVOICE** in the COD confirmation email. It opens the existing
   invoice design at a signed URL without login. Also paste the same link into a
   private/incognito window to verify guest access. Confirm the order number,
   products, quantities, prices, delivery address, shipping and total.
5. Click **Print / Save as PDF**, then select **Save as PDF** in the browser print
   dialog. No EmailJS attachment or paid feature is used.
6. Refresh the confirmation page or recheck the verified payment: it must not
   send another email. Welcome emails still use the existing Django mailer.
7. To inspect only delivery status (no credentials), run:
   `venv\Scripts\python.exe manage.py shell -c "from orders.models import OrderConfirmationEmail; print(list(OrderConfirmationEmail.objects.values_list('order__order_number', 'status', 'error_code')))"`.

Orders are committed before delivery. HTTP has bounded timeouts, but the checkout
response may wait for the send. `SENT` means EmailJS accepted the email, not guaranteed inbox delivery.
`PENDING` can be processed with `manage.py send_order_confirmations` after fixing
configuration. This command spaces sends by more than one second. Concurrent
checkouts may hit EmailJS's one-request-per-second limit (`HTTP_429`).
`FAILED` means a non-200 response; `UNKNOWN` means acceptance could not be determined.
`SENDING` may remain after a process crash. These states are never automatically
resent. Check EmailJS history before any staff-controlled retry; the official API
has no documented idempotency key, so exactly-once delivery across crashes cannot
be guaranteed. The database's conditional claim prevents concurrent duplicate sends.

## Secure invoice button

The EmailJS template button must use `<a href="{{invoice_url}}">VIEW YOUR INVOICE</a>`.
`invoice_url` now contains a Django TimestampSigner token scoped to the order's
database ID, customer ID and order number. Access requires the full valid signed
link, not a predictable order number. The token expires seven days after it is
generated for sending. Invalid, altered and expired tokens return 404.
The signed route needs no session, so customers can open it while signed out.
The existing checkout still requires login; this change does not add guest
checkout creation. Existing authenticated customer/owner/staff invoice routes
keep their permissions. Signed responses disable caching, indexing and referrer
sharing. Anyone who possesses the valid email link can open that one invoice.

Set `BRAMANDA_PUBLIC_BASE_URL=http://127.0.0.1:8000` in `.env` for localhost,
then restart Django. A saved public URL takes precedence over the old
`PUBLIC_BASE_URL` setting for invoice emails. An origin with a path, query,
credentials, whitespace or invalid port blocks email sending.
Keep the private `INVOICE_SIGNING_KEY` in `.env` stable. A random key was added
locally when absent so public links do not rely on the known Django development
secret. Removing it prevents invoice email sending; changing it invalidates
existing links. No key values should be copied into source control.

The final invoice URL is validated before EmailJS is called. Missing, malformed,
expired, or wrong-order invoice URLs leave delivery pending with
`PREPARATION_FAILED`, preserving the successful order. Fix the configuration
and run `manage.py send_order_confirmations` for pending deliveries.
Existing sent orders are not resent; place a new order to test the new button.
No PDF rendering dependency or attachment parameter is used. Browser printing
reuses `templates/payments/document.html` and the existing print stylesheet.
Localhost links work on the computer running Django; keep the server running
when opening the email button.

Official references:
- https://www.emailjs.com/docs/rest-api/send/
- https://docs.djangoproject.com/en/6.0/topics/signing/
- https://github.com/emailjs-com/emailjs-nodejs#api-calls-are-disabled-for-non-browser-applications
