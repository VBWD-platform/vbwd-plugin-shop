"""S117 — drop the redundant ``is_digital`` boolean from ``shop_product``.

The S116 product-type system (``product_type_slug``) now carries the "digital
product" meaning: ``is_digital == True`` is exactly equivalent to
``product_type_slug == "digital"``. The old boolean is redundant, so it is
removed. The two behaviours it drove (checkout stock-skip, fe "always in stock")
are re-keyed onto ``product_type_slug == "digital"`` in the plugin code.

No data backfill is needed here: the demo seed and any prior digital products
are re-typed via ``product_type_slug`` in application code. ``downgrade`` re-adds
the column with its original non-null default of ``False``.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260705_shop_drop_is_digital"
down_revision = "20260705_shop_prod_type_cols"
branch_labels = None
depends_on = None

_TABLE = "shop_product"
_COLUMN = "is_digital"


def upgrade() -> None:
    op.drop_column(_TABLE, _COLUMN)


def downgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
