"""S85.1 — the shop price-storage migration is wired into the plugin's own chain.

It anchors on the shop plugin's prior head (no cross-plugin anchor), widens
every money column to ``Float``, and drops the redundant ``currency`` (product +
order) and the lossy ``price_float`` mirror (product).
"""
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/shop
MIGRATION = PLUGIN_ROOT / "migrations/versions/20260613_shop_price_float.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_migration_exists_and_chains_off_shop_prior_head():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260613_shop_price_float"
    # Anchors on shop's own prior head (the product display-mode migration).
    assert down == "20260612_shop_prod_disp_mode"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN


def test_migration_widens_money_columns_to_float():
    src = MIGRATION.read_text()
    assert "sa.Float()" in src
    # Order + order-item money fields are migrated too.
    for column_name in ("subtotal", "tax_amount", "total_amount", "shipping_cost"):
        assert column_name in src
    for column_name in ("unit_price", "total_price"):
        assert column_name in src


def test_migration_drops_dead_columns():
    src = MIGRATION.read_text()
    assert 'drop_column(PRODUCT_TABLE, "currency")' in src
    assert 'drop_column(PRODUCT_TABLE, "price_float")' in src
    assert 'drop_column(ORDER_TABLE, "currency")' in src
