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
