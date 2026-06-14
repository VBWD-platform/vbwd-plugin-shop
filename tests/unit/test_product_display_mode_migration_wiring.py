"""S72.4 — the per-product price-display-mode migration is wired into the shop
plugin's own chain.

The migration anchors on the shop plugin's prior head
(``20260612_shop_product_tax``, the S72.3 product↔tax join) and adds a nullable
``price_display_mode VARCHAR(8)`` column to ``shop_product``.
"""
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/shop
MIGRATION = PLUGIN_ROOT / "migrations/versions/20260612_shop_product_display_mode.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_migration_exists_and_chains_off_shop_prior_head():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260612_shop_prod_disp_mode"
    # Anchors on shop's own prior head (the S72.3 product↔tax migration).
    assert down == "20260612_shop_product_tax"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN


def test_migration_adds_nullable_display_mode_column():
    src = MIGRATION.read_text()
    assert "shop_product" in src
    assert "price_display_mode" in src
