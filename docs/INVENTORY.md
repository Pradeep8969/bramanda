# Manual stock adjustments

Stock is stored in `ProductVariant.stock_quantity`, which defaults to zero. The
Django admin field is read-only so stock changes go through
`inventory.services.adjust_stock` and retain their transaction history.

To receive stock:

1. Sign in with an active OWNER account and open **Owner Dashboard → Inventory**
   at `/owner/inventory/`. Active STAFF accounts use `/staff/inventory/`.
2. In **Adjust stock**, select the exact product/color/size variant.
3. Enter a positive **Quantity Change**, such as `10` to add ten units.
4. Enter a **Reason / Note** and click **Submit Adjustment**.

This adds to the current quantity rather than setting an absolute total. Negative
changes remove units but cannot bring stock below zero. Owners can select inactive
variants; staff can adjust only active variants.

Review stock history in **Django Admin → Inventory → Inventory transactions**
at `/admin/inventory/inventorytransaction/` (requires admin access and view
permission). Each record includes the variant, signed quantity, previous/new
stock, actor, timestamp and reason. Dashboard activity is recorded atomically too.
History is read-only in admin.

The form's hidden adjustment key has a database uniqueness constraint: double
clicks and replayed submissions cannot apply the same adjustment twice. After a
successful save, open the inventory page again for a new adjustment. Validation
failures roll back stock and history together. Authentication, role checks,
POST-only handling and CSRF protection apply to both dashboard routes.

Checkout and verified payment failure stock reservation and release continue using
the existing inventory service. Manual adjustments do not change order status or
payment records.

For another installation, apply the additive schema migration before running
the updated code:

```powershell
python manage.py migrate inventory
```
