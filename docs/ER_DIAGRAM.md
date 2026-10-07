# Entity relationship diagram

This diagram represents the custom business models in the inspected `models.py` files. Fields shown are selected real stored fields, not an exhaustive schema. `id` is Django's automatic primary key. `_id` names represent the database columns for actual foreign-key fields. Mermaid types are simplified logical types. User is `accounts.User`, extending Django AbstractUser.

```mermaid
erDiagram
    User ||--o| Cart : owns
    User ||--o{ Order : places
    User |o--o{ InventoryTransaction : created_by
    User |o--o{ StaffActivity : staff
    Category ||--o{ Product : contains
    Product ||--o{ ProductImage : images
    Product ||--o{ ProductVariant : variants
    Size ||--o{ ProductVariant : size
    Color ||--o{ ProductVariant : color
    Cart ||--o{ CartItem : items
    ProductVariant ||--o{ CartItem : variant
    Order ||--o{ OrderItem : items
    Product |o--o{ OrderItem : product
    ProductVariant |o--o{ OrderItem : variant
    ProductVariant ||--o{ InventoryTransaction : history

    User {
        bigint id PK
        string username UK
        string password
        string email
        string role
        string phone_number
        text address
    }
    Category {
        bigint id PK
        string name UK
        string slug UK
        text description
        boolean is_active
    }
    Product {
        bigint id PK
        bigint category_id FK
        string name
        string slug UK
        decimal price
        string image
        boolean is_active
        boolean featured
    }
    ProductImage {
        bigint id PK
        bigint product_id FK
        string image
        string alt_text
        int display_order
    }
    Size {
        bigint id PK
        string name UK
        int display_order
        boolean is_active
    }
    Color {
        bigint id PK
        string name UK
        string hex_code
        boolean is_active
    }
    ProductVariant {
        bigint id PK
        bigint product_id FK
        bigint size_id FK
        bigint color_id FK
        string sku UK
        int stock_quantity
        boolean is_active
    }
    Cart {
        bigint id PK
        bigint user_id FK,UK
        datetime created_at
        datetime updated_at
    }
    CartItem {
        bigint id PK
        bigint cart_id FK
        bigint variant_id FK
        int quantity
    }
    Order {
        bigint id PK
        bigint customer_id FK
        string order_number UK
        text shipping_address
        decimal subtotal
        decimal shipping_cost
        decimal grand_total
        string payment_method
        string payment_status
        string order_status
        string delivery_status
    }
    OrderItem {
        bigint id PK
        bigint order_id FK
        bigint product_id FK
        bigint variant_id FK
        string product_name
        string size_name
        string color_name
        string sku
        int quantity
        decimal unit_price
        decimal subtotal
    }
    InventoryTransaction {
        bigint id PK
        bigint variant_id FK
        bigint created_by_id FK
        string transaction_type
        int quantity
        int previous_stock
        int new_stock
        string reference
        text note
    }
    StaffActivity {
        bigint id PK
        bigint staff_id FK
        string action
        text description
        string reference
        datetime created_at
    }
```

## Relationship explanations

| Relationship | Cardinality and deletion behavior |
| --- | --- |
| User → Cart | A user has zero or one cart; every cart has exactly one user. OneToOneField with CASCADE. |
| User → Order | A user can have many orders; every order requires one customer. ForeignKey with PROTECT. The field itself does not restrict the user's role at database level. |
| User → InventoryTransaction | A user can create many inventory records; created_by is optional and uses SET_NULL. |
| User → StaffActivity | A user can be referenced by many activities; staff is nullable and uses SET_NULL. The name does not impose a database role constraint. |
| Category → Product | A category can contain many products; every product requires one category. PROTECT. |
| Product → ProductImage | A product can have many gallery images; every image belongs to one product. CASCADE. |
| Product → ProductVariant | A product can have many variants; every variant belongs to one product. CASCADE, subject to other protected dependencies. |
| Size → ProductVariant | A size can be used by many variants; every variant requires one size. PROTECT. |
| Color → ProductVariant | A color can be used by many variants; every variant requires one color. PROTECT. |
| Cart → CartItem | A cart can contain many items; every item requires one cart. CASCADE. |
| ProductVariant → CartItem | A variant can appear in many carts; each cart item requires one variant. PROTECT. A cart/variant pair is unique. |
| Order → OrderItem | An order can have many item records; every item requires one order. CASCADE. Checkout creates at least one item, but the foreign key does not enforce that minimum. |
| Product → OrderItem | A product can be referenced by many historical items; the product link is optional and uses SET_NULL. |
| ProductVariant → OrderItem | A variant can be referenced by many historical items; the variant link is optional and uses SET_NULL. Stored snapshot values preserve history. |
| ProductVariant → InventoryTransaction | A variant can have many stock-history entries; every entry requires one variant. PROTECT. |

ProductVariant additionally has a unique constraint on `(product, size, color)`. OrderItem's product and variant are separate foreign keys; the schema does not define a composite foreign-key constraint between them. Checkout assigns consistent references.

InventoryTransaction.reference and StaffActivity.reference are strings, often containing an order number or SKU. They are not relational foreign keys. There is no Payment model or separate Customer/Staff/Owner entity. Inherited Django auth group/permission relationships and framework tables are outside this business diagram; see [Database design](DATABASE.md).
