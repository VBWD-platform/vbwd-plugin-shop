"""S85.1 — shop price storage migration (D4/D5).

Widens every shop money column from ``Numeric(10, 2)`` to ``double precision``
(``db.Float``) — prices are full precision and never rounded in code (D4):

* ``shop_product.price``
* ``shop_order.subtotal`` / ``tax_amount`` / ``total_amount`` / ``shipping_cost``
* ``shop_order_item.unit_price`` / ``total_price``

Drops the redundant ``currency`` from ``shop_product`` and ``shop_order`` (D5) —
the single source of truth for the operating currency is the global
``default_currency`` core setting (S84). Drops the lossy ``price_float`` mirror
from ``shop_product`` (D5); the single ``price`` double is enough.

Anchors on the shop plugin's own current head so the chain resolves with the
shop plugin alone. ``downgrade`` re-narrows to ``Numeric(10, 2)`` and re-adds the
dropped columns.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260613_shop_price_float"
down_revision = "20260612_shop_prod_disp_mode"
branch_labels = None
depends_on = None

PRODUCT_TABLE = "shop_product"
ORDER_TABLE = "shop_order"
ORDER_ITEM_TABLE = "shop_order_item"

_PRODUCT_PRICE_COLUMNS = ("price",)
_ORDER_PRICE_COLUMNS = ("subtotal", "tax_amount", "total_amount", "shipping_cost")
_ORDER_ITEM_PRICE_COLUMNS = ("unit_price", "total_price")


def _widen_to_float(table_name: str, column_names) -> None:
    for column_name in column_names:
        op.alter_column(
            table_name,
            column_name,
            type_=sa.Float(),
            existing_type=sa.Numeric(10, 2),
            postgresql_using=f"{column_name}::double precision",
        )


def _narrow_to_numeric(table_name: str, column_names) -> None:
    for column_name in column_names:
        op.alter_column(
            table_name,
            column_name,
            type_=sa.Numeric(10, 2),
            existing_type=sa.Float(),
            postgresql_using=f"{column_name}::numeric(10,2)",
        )


def upgrade() -> None:
    _widen_to_float(PRODUCT_TABLE, _PRODUCT_PRICE_COLUMNS)
    _widen_to_float(ORDER_TABLE, _ORDER_PRICE_COLUMNS)
    _widen_to_float(ORDER_ITEM_TABLE, _ORDER_ITEM_PRICE_COLUMNS)

    op.drop_column(PRODUCT_TABLE, "currency")
    op.drop_column(PRODUCT_TABLE, "price_float")
    op.drop_column(ORDER_TABLE, "currency")


def downgrade() -> None:
    op.add_column(
        ORDER_TABLE,
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="EUR"
        ),
    )
    op.add_column(
        PRODUCT_TABLE,
        sa.Column("price_float", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        PRODUCT_TABLE,
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="EUR"
        ),
    )

    _narrow_to_numeric(ORDER_ITEM_TABLE, _ORDER_ITEM_PRICE_COLUMNS)
    _narrow_to_numeric(ORDER_TABLE, _ORDER_PRICE_COLUMNS)
    _narrow_to_numeric(PRODUCT_TABLE, _PRODUCT_PRICE_COLUMNS)
