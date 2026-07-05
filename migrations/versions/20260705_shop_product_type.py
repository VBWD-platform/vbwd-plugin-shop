"""S116.1 — the ``shop_product_type`` table (typed products, field clusters).

A product type is a named additive cluster of custom fields layered on the base
product; it carries NO behaviour columns. Rows are either reconciled from a code
registry (``source='plugin'``, read-only in the UI) or created by an admin
(``source='admin'``, fully editable).

Anchors on the shop plugin's own current head (``20260701_shop_product_vendor_id``)
so the chain resolves with the shop plugin alone (core stays standalone-resolvable).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260705_shop_product_type"
down_revision = "20260701_shop_product_vendor_id"
branch_labels = None
depends_on = None

_TABLE = "shop_product_type"
_SLUG_INDEX = "ix_shop_product_type_slug"
_ACTIVE_INDEX = "ix_shop_product_type_is_active"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "product_type_fields",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("slug", name="uq_shop_product_type_slug"),
    )
    op.create_index(_SLUG_INDEX, _TABLE, ["slug"])
    op.create_index(_ACTIVE_INDEX, _TABLE, ["is_active"])


def downgrade() -> None:
    op.drop_index(_ACTIVE_INDEX, table_name=_TABLE)
    op.drop_index(_SLUG_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
