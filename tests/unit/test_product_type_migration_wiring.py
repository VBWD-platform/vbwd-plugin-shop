"""S116.1 — the product-type migrations are wired into the shop plugin's chain.

Two migrations, each anchored on the shop plugin's own prior head so the chain
resolves with the shop plugin alone (core stays standalone-resolvable):
  - ``20260705_shop_product_type``      → the ``shop_product_type`` table.
  - ``20260705_shop_prod_type_cols``    → the two ``shop_product`` columns.
"""
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/shop
VERSIONS = PLUGIN_ROOT / "migrations/versions"
TABLE_MIGRATION = VERSIONS / "20260705_shop_product_type.py"
COLS_MIGRATION = VERSIONS / "20260705_shop_product_type_cols.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def _revision(src):
    return re.search(r'^revision = "([^"]+)"', src, re.M).group(1)


def _down_revision(src):
    return re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)


def test_table_migration_chains_off_shop_prior_head():
    src = TABLE_MIGRATION.read_text()
    revision = _revision(src)
    assert revision == "20260705_shop_product_type"
    assert _down_revision(src) == "20260701_shop_product_vendor_id"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN
    assert "shop_product_type" in src


def test_cols_migration_chains_off_the_table_migration():
    src = COLS_MIGRATION.read_text()
    revision = _revision(src)
    assert revision == "20260705_shop_prod_type_cols"
    assert _down_revision(src) == "20260705_shop_product_type"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN
    assert "product_type_slug" in src
    assert "type_field_values" in src
