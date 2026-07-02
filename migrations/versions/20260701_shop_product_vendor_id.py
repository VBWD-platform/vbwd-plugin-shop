"""Vendor-mode — add ``shop_product.vendor_id`` (nullable, indexed FK).

Adds the owning vendor's ``vbwd_user`` id to products. ``NULL`` is a
platform-owned product (the classic single-owner shop). The FK is
``ON DELETE SET NULL`` so removing a user reverts their products to the platform
rather than cascading a catalog delete; a btree index backs the vendor's
"my products" filter.

Anchors on the shop plugin's own current head so the chain resolves with the
shop plugin alone (core stays standalone-resolvable).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260701_shop_product_vendor_id"
down_revision = "20260617_shop_link_product_id_idx"
branch_labels = None
depends_on = None

_TABLE = "shop_product"
_COLUMN = "vendor_id"
_INDEX = "ix_shop_product_vendor_id"
_FK = "fk_shop_product_vendor_id_user"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, UUID(as_uuid=True), nullable=True))
    op.create_index(_INDEX, _TABLE, [_COLUMN])
    op.create_foreign_key(
        _FK,
        _TABLE,
        "vbwd_user",
        [_COLUMN],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
