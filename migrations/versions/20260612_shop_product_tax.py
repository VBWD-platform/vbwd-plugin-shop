"""S72.3 — product↔tax M2M join table.

Creates ``shop_product_tax`` linking ``shop_product`` to the CORE tax catalog
(``vbwd_tax``). The ``tax_id`` FK is ``ON DELETE RESTRICT`` so deleting a tax
that is assigned to a product is rejected by the database (a clean block, never
a silent cascade); ``product_id`` is ``ON DELETE CASCADE`` so deleting a product
tidies its own links.

The shop plugin has no prior migration chain of its own — its base tables ship
in the core monolith — so this anchors on the last core revision that touches
the tax catalog (``20260404_1500``, which adds the tax class and finalises
``vbwd_tax``). Core revisions are always present, so the migration stays
resolvable regardless of which other plugins are installed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "20260612_shop_product_tax"
down_revision = "20260404_1500"
branch_labels = None
depends_on = None

TABLE = "shop_product_tax"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("shop_product.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tax_id",
            UUID(as_uuid=True),
            sa.ForeignKey("vbwd_tax.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
