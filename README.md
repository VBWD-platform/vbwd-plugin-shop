# vbwd-plugin-ecommerce

E-commerce plugin -- products, orders, stock management, coupons, reviews, wishlist.

## Structure

```
plugins/ecommerce/
├── __init__.py                  # EcommercePlugin(BasePlugin)
├── populate_db.py               # Demo data (idempotent)
├── ecommerce/                   # Source code
│   ├── models/
│   │   ├── product.py           # Product (name, slug, sku, price, variants flag)
│   │   ├── product_variant.py   # ProductVariant (size, colour, sku override)
│   │   ├── product_category.py  # ProductCategory (tree via parent_id)
│   │   ├── product_type.py      # ProductType (S116.1: named additive field cluster)
│   │   ├── product_image.py     # ProductImage (url, sort_order)
│   │   ├── warehouse.py         # Warehouse (name, address, is_active)
│   │   ├── warehouse_stock.py   # WarehouseStock (quantity, reserved, per-warehouse)
│   │   ├── stock_block.py       # StockBlock (temporary reservation during checkout)
│   │   ├── order.py             # Order (order_number, status, totals, tracking)
│   │   ├── order_item.py        # OrderItem (product snapshot, quantity, prices)
│   │   ├── discount.py          # Discount + Coupon + CouponUsage
│   │   ├── review.py            # Review (rating, text, moderation status)
│   │   ├── wishlist.py          # Wishlist (user + product)
│   │   └── abandoned_cart.py    # AbandonedCart (recovery tracking)
│   ├── repositories/
│   │   ├── product_repository.py
│   │   ├── product_category_repository.py
│   │   ├── warehouse_repository.py
│   │   ├── warehouse_stock_repository.py
│   │   ├── stock_block_repository.py
│   │   ├── order_repository.py
│   │   └── order_item_repository.py
│   ├── services/
│   │   ├── stock_service.py     # Block, commit, release, restore, cleanup
│   │   └── discount_service.py  # Calculate discounts, validate/redeem coupons
│   ├── handlers/
│   │   └── line_item_handler.py # EcommerceLineItemHandler (CUSTOM line items)
│   └── routes.py                # Public + admin endpoints
└── tests/
    ├── unit/
    │   ├── test_models.py
    │   ├── test_stock_service.py
    │   ├── test_discount_service.py
    │   └── test_line_item_handler.py
    └── integration/
```

## Development

```bash
# Unit tests
docker compose run --rm test pytest plugins/ecommerce/tests/unit/ -v

# Integration tests
docker compose run --rm test pytest plugins/ecommerce/tests/integration/ -v

# Single test file
docker compose run --rm test pytest plugins/ecommerce/tests/unit/test_stock_service.py -v
```

## API Routes

### Public -- Product Catalog

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/shop/products` | Product list (search, category filter, pagination) |
| GET | `/api/v1/shop/products/<slug>` | Product detail (images, variants, stock status) |
| GET | `/api/v1/shop/categories` | Category tree |
| GET | `/api/v1/shop/categories/<slug>` | Category detail |

### Public -- Orders (authenticated)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/shop/orders` | User's order history |
| GET | `/api/v1/shop/orders/<order_id>` | Order detail (owner only) |

### Public -- Coupons

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/shop/coupons/validate` | Validate coupon code against cart total |

### Admin -- Products

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/shop/products` | All products (including inactive) |
| POST | `/api/v1/admin/shop/products` | Create product |
| GET | `/api/v1/admin/shop/products/<id>` | Product detail |
| PUT | `/api/v1/admin/shop/products/<id>` | Update product |
| DELETE | `/api/v1/admin/shop/products/<id>` | Delete product |

### Admin -- Product variants (S101.0, perm `shop.products.manage`)

The backend variant-authoring API: create/edit/reorder/toggle a product's pack
variants programmatically (each priced via the core `PriceFactory`, stock via
the existing variant-aware `WarehouseStock`). Stays vertical-agnostic — a
downstream module (e.g. a pharmacy module) drives it from its own UI.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/shop/products/<id>/variants` | List variants (ordered) |
| POST | `/api/v1/admin/shop/products/<id>/variants` | Create a variant |
| PUT | `/api/v1/admin/shop/products/<id>/variants/<variant_id>` | Update a variant |
| DELETE | `/api/v1/admin/shop/products/<id>/variants/<variant_id>` | Delete a variant |
| POST | `/api/v1/admin/shop/products/<id>/variants/reorder` | Reorder by `variant_ids[]` |
| POST | `/api/v1/admin/shop/products/<id>/variants/<variant_id>/toggle` | Flip `is_active` |

Also adds a generic, vertical-agnostic **checkout-validation registry**
(`shop/checkout_validation_registry.py`): the cart-checkout route runs every
registered validator BEFORE blocking stock (fail-closed). Shop ships none; a
downstream module registers its own purchase gates without editing shop.

### Admin -- Product types (S116.1, perm `shop.products.manage`)

A **product type** is a named, *additive cluster of custom fields* layered on the
universal base product. It carries **no behaviour columns** — fields only. A
product references at most one type via `Product.product_type_slug` (nullable;
`NULL` = the simple default product, base fields only) and stores its per-product
answers in `Product.type_field_values` (JSONB). Types live in the
`shop_product_type` table; the field cluster is a list of descriptors:

```json
{
  "slug": "download_url",
  "type": "url",
  "label": "Download URL",
  "required": false,
  "options": [],          // for select / multiselect
  "help": "Where the buyer downloads the product after purchase.",
  "sort_order": 0
}
```

Supported field `type`s: `string` / `text` / `url` / `textarea`, `integer`,
`number` / `float` / `decimal`, `boolean`, `select`, `multiselect`. Unknown
types pass through unchecked (forward-compatible). On save,
`services/product_type_service.validate_type_field_values()` enforces that
required fields are present, each value matches its declared type, and
`select` / `multiselect` values are drawn from the field's `options` (violations
→ 400).

**Two provenance modes** (`ProductType.source`):

- `admin` — created via the API/UI below; fully editable and deletable.
- `plugin` — registered from code (see below) and **read-only in the UI**
  (`PUT` / `DELETE` return 409); the owning plugin owns the cluster.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/shop/product-types` | Public: active types (for storefront/forms) |
| GET | `/api/v1/shop/product-types/<slug>` | Public: single type |
| GET | `/api/v1/admin/shop/product-types` | All types (including inactive) |
| POST | `/api/v1/admin/shop/product-types` | Create an `admin`-sourced type |
| PUT | `/api/v1/admin/shop/product-types/<slug>` | Update (409 on a `plugin` type) |
| DELETE | `/api/v1/admin/shop/product-types/<slug>` | Delete (409 on a `plugin` type) |

Create body (POST): `{name, slug, description?, is_active?, product_type_fields[]}`.

**Plugin-owned types (OCP seam).** A plugin's `on_enable` calls
`services/product_type_registry.register_product_type(descriptor)`; on the shop
plugin's enable, `reconcile_product_types()` upserts every registered descriptor
into `shop_product_type` idempotently (`source='plugin'`, read-only in the UI).
Shop self-registers a `digital` type (`DIGITAL_TYPE_DESCRIPTOR`) as the reference
example — adding a type never edits shop. Reconcile rules: unknown slug → insert;
existing `plugin` row → overwrite name/description/fields; existing `admin` row →
never clobbered.

Migrations: `20260705_shop_product_type` (the `shop_product_type` table) and
`20260705_shop_product_type_cols` (`product_type_slug` + `type_field_values` on
`shop_product`).

### Admin -- Orders

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/shop/orders` | All orders (status filter) |
| GET | `/api/v1/admin/shop/orders/<id>` | Order detail |
| POST | `/api/v1/admin/shop/orders/<id>/ship` | Mark as shipped (tracking info) |
| POST | `/api/v1/admin/shop/orders/<id>/complete` | Mark as completed |

### Admin -- Warehouses and Stock

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/shop/warehouses` | List warehouses |
| GET | `/api/v1/admin/shop/warehouses/<id>` | Warehouse detail with stock levels |

## Configuration

Default values in `__init__.py`:

| Key | Default | Description |
|-----|---------|-------------|
| `currency` | `"EUR"` | Default currency |
| `stock_block_ttl_minutes` | `5` | Minutes before stock reservation expires |
| `low_stock_threshold_default` | `10` | Low-stock alert threshold |
| `enable_warehouses` | `true` | Multi-warehouse support |
| `enable_digital_products` | `true` | Allow digital product type |
| `order_number_prefix` | `"ORD"` | Prefix for order numbers |
| `tax_included_in_price` | `true` | Prices include tax |
| `max_cart_items` | `50` | Maximum items per cart |
| `guest_checkout_enabled` | `true` | Allow guest checkout |

## Line Item Integration

The plugin uses **CUSTOM** line items with `metadata.plugin = "ecommerce"`. When core processes an invoice payment:

1. `EcommerceLineItemHandler.can_handle_line_item()` checks `item_type == CUSTOM` and `extra_data.plugin == "ecommerce"`
2. `activate_line_item()` -- commits stock blocks, creates Order + OrderItem, publishes `order.created`
3. `reverse_line_item()` -- sets order to REFUNDED, restores stock, publishes `order.refunded`
4. `restore_line_item()` -- re-confirms order after refund reversal

## Dependencies

- `email` plugin (for order notification emails)
