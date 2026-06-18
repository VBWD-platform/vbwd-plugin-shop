"""S89 — index ``shop_product_category_link.product_id`` (cascade-delete fix).

The product↔category M2M link table has only its composite primary key
``(category_id, product_id)``; ``product_id`` is the *second* column, so it has
no usable standalone index. Every other FK table referencing ``shop_product``
(variants, images, reviews, stock, wishlist, order items, tax) already carries
such an index — this link table was the lone gap.

Without it, deleting a parent product fires the ``ON DELETE CASCADE`` action
``DELETE FROM shop_product_category_link WHERE product_id = $1`` once per deleted
row, and each fires a **sequential scan** of the link heap. During the
load-test reset (``data-exchange bulk-seed shop_products --count 0 --reset``) the
set-based pre-clear deletes the load-test link rows in the *same* transaction,
but those dead tuples stay physically in the heap until commit/vacuum — so the
per-row cascade still seq-scans the full link table → **O(N²)**. At the t3 (1M)
tier this overran the bench's 1800s reset budget (measured: 50k reset 21s → 3.6s
with this index; the curve flips from quadratic to linear).

Adds the missing btree index so the cascade becomes an index probe (O(N log N)).
Anchors on the shop plugin's own current head so the chain resolves with the
shop plugin alone.
"""
from alembic import op

revision = "20260617_shop_link_product_id_idx"
down_revision = "20260613_shop_price_float"
branch_labels = None
depends_on = None

_TABLE = "shop_product_category_link"
_INDEX = "ix_shop_product_category_link_product_id"
_COLUMN = "product_id"


def upgrade() -> None:
    op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
