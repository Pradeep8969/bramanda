# Database design

The configured database is SQLite at `BASE_DIR / db.sqlite3`. Django's ORM maps Python model instances to database records. Most business models have an automatically generated primary key. The [ER diagram](ER_DIAGRAM.md) shows their relationships.

## Major models

| Model | Purpose | Important stored fields | Relationships |
| --- | --- | --- | --- |
| User | One account model for customers, staff, and owners | Inherited username/password/name/email/auth flags; role, phone_number, address | Optional reusable cart; many orders, inventory records, and staff activities |
| Category | Organize clothing products | Unique name and slug, description, is_active, timestamps | Many products; a product requires one category |
| Product | General catalog item and common selling price | Name, unique slug, description, price, image, is_active, featured, timestamps | One category; many gallery images and variants; optional references from historical order items |
| ProductImage | Additional product gallery image | Image path, alt_text, display_order | One product |
| Size | Reusable clothing size | Unique name, display_order, is_active | Many variants |
| Color | Reusable color | Unique name, optional validated hex_code, is_active | Many variants |
| ProductVariant | One purchasable product/size/color combination | Unique sku, stock_quantity, is_active, timestamps | One product, size, and color; many cart items, order items, and inventory transactions |
| Cart | Reusable basket belonging to an account | User, timestamps | At most one per user; many cart items |
| CartItem | Quantity of a chosen variant in a basket | Quantity, timestamps | One cart and one variant |
| Order | Purchase record and shipping/payment/fulfillment information | Unique order_number, recipient names/email/phone/shipping_address, subtotal, shipping_cost, grand_total, payment_method, payment_status, order_status, delivery_status, timestamps | One customer User; many order items |
| OrderItem | Historical purchase line | Product/size/color names, sku, quantity, unit_price, subtotal | One order; optional product and variant links |
| InventoryTransaction | Audit record for a stock change | transaction_type, signed quantity, previous_stock, new_stock, reference, note, created_at | One protected variant; optional created_by User |
| StaffActivity | Record selected operational actions | action, description, reference, created_at | Optional staff User; no direct order or inventory foreign key |

## Important design choices

**Variant stock:** stock is held on ProductVariant rather than Product because Black/M and Beige/L can have different availability. The product/size/color combination is unique, and each SKU is unique. Product price is shared by its variants; there is no separate variant-price field.

**Cart totals:** Cart subtotal/item count and CartItem unit price/subtotal are computed properties, not stored columns. Cart pricing reflects the current Product price. A cart contains at most one item per variant and requires positive quantities.

**Order snapshots:** Order stores the submitted recipient and address separately from the user's profile. OrderItem stores names, SKU, and money amounts at checkout. Later catalog edits therefore do not rewrite purchase history. Product and variant links use SET_NULL if deletion is otherwise allowed, while the snapshot remains. Inventory references may independently prevent deletion of a variant.

**Money and constraints:** prices and monetary totals use DecimalField. Database checks reject negative product/order money values and nonpositive cart/order-item quantities. Forms and services add validation before writes.

**Inventory ledger:** a transaction has a signed quantity change: positive adds stock, negative removes it. The database requires `new_stock = previous_stock + quantity` and a valid transaction type. Supported types are STOCK_IN, STOCK_OUT, ADJUSTMENT, ORDER, and RETURN. The service changes the variant stock and writes history atomically; saving a history record alone does not change stock.

**Payments:** no Payment model exists. Order supports COD as its only payment-method choice and stores PENDING/PAID/FAILED/REFUNDED payment statuses. The operational payment form offers the COD PAID action; the other model choices do not imply gateway or refund-processing features.

**Deletion policy:** PROTECT prevents deletion of referenced categories, sizes/colors, cart variants, inventory variants, and order customers. CASCADE removes dependent product images/variants, cart items, or order items when their parent can be deleted. SET_NULL preserves audit records when their optional user reference is removed. Existing protected dependencies can prevent a cascading deletion.

## Django-provided tables and file storage

User inherits Django's group and user-permission relationships from AbstractUser. Django also maintains permission/content-type, group, session, admin log, and migration tables. Application dashboard authorization is based on `User.role`, not a custom Role table. No separate Customer, Staff, Owner, payment, delivery-tracking-event, or report model exists.

Images are files under `media/products/` and `media/products/gallery/`; image fields store their paths. Reports query current orders/items rather than a separate analytics database. BRAMANDA's custom database models and migrations remain unchanged by the social-login extension.

## Social authentication extension

Google/Facebook login adds allauth's packaged models: SocialApp stores provider configuration/credentials, SocialAccount links a provider UID to the existing User, SocialToken represents provider tokens when storage is enabled, and EmailAddress/EmailConfirmation support account email handling. Provider/UID pairs identify returning social users; equal email addresses do not automatically merge accounts. Token persistence remains disabled by allauth's default. These packaged migrations add tables without altering BRAMANDA's custom model schema. Sites is not enabled, so SocialApp has no Site association in this configuration. See [Social login](SOCIAL_LOGIN.md).
