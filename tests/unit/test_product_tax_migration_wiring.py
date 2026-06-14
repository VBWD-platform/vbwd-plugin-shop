"""S72.3 — the product↔tax join-table migration is wired into the shop plugin.

The migration lives in the shop plugin's own ``migrations/versions`` directory,
anchors on the last core revision that touches the tax catalog (shop has no
prior plugin migration of its own — its tables ship in the core monolith), and
creates ``shop_product_tax`` with an ``ON DELETE RESTRICT`` FK to the CORE
``vbwd_tax`` catalog and an ``ON DELETE CASCADE`` FK to ``shop_product``.
"""
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]  # plugins/shop
MIGRATION = PLUGIN_ROOT / "migrations/versions/20260612_shop_product_tax.py"

ALEMBIC_VERSION_NUM_MAXLEN = 32


def test_migration_exists_and_anchors_on_a_resolvable_revision():
    src = MIGRATION.read_text()
    revision = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert revision == "20260612_shop_product_tax"
    # Anchors on the last core tax revision (shop has no prior plugin head).
    assert down == "20260404_1500"
    assert len(revision) <= ALEMBIC_VERSION_NUM_MAXLEN


def test_migration_creates_join_table_with_restrict_and_cascade_fks():
    src = MIGRATION.read_text()
    assert "shop_product_tax" in src
    assert "vbwd_tax.id" in src
    assert "RESTRICT" in src
    assert "shop_product.id" in src
    assert "CASCADE" in src
