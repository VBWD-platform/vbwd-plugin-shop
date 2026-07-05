"""S116.1 — add ``product_type_slug`` + ``type_field_values`` to ``shop_product``.

``product_type_slug`` is a nullable soft-ref to ``shop_product_type.slug`` (loose
coupling, NOT a hard FK). ``NULL`` = the simple default product (base fields
only). ``type_field_values`` (JSONB, default ``{}``) holds per-product values
keyed by the type's field slugs.

**No backfill** — existing rows stay ``NULL`` = base-only simple products, zero
behaviour change. Anchors on the ``shop_product_type`` table migration so the
column soft-ref target exists in the chain first.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260705_shop_prod_type_cols"
down_revision = "20260705_shop_product_type"
branch_labels = None
depends_on = None

_TABLE = "shop_product"
_SLUG_COLUMN = "product_type_slug"
_VALUES_COLUMN = "type_field_values"
_SLUG_INDEX = "ix_shop_product_product_type_slug"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_SLUG_COLUMN, sa.String(length=100), nullable=True),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            _VALUES_COLUMN,
            JSONB(),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(_SLUG_INDEX, _TABLE, [_SLUG_COLUMN])


def downgrade() -> None:
    op.drop_index(_SLUG_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _VALUES_COLUMN)
    op.drop_column(_TABLE, _SLUG_COLUMN)
