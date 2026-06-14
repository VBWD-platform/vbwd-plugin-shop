"""S72.4 — per-product price-display-mode persistence + migration (integration).

Covers the contract end-to-end against the real schema:
- ``price_display_mode`` defaults to ``NULL`` (inherit global) and persists an
  override (``"netto"``/``"brutto"``),
- ``to_dict()`` reflects the stored value,
- the migration adds the column on ``upgrade`` and drops it on ``downgrade``
  (up→down→up clean).
"""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import inspect

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.repositories.product_repository import ProductRepository


def _product(db, slug: str, price_display_mode=None) -> Product:
    product = Product(
        id=uuid4(),
        name=slug.title(),
        slug=slug,
        price=Decimal("100.00"),
        price_display_mode=price_display_mode,
    )
    db.session.add(product)
    db.session.flush()
    return product


def test_default_is_null_inherit(db):
    product = _product(db, f"inherit-{uuid4().hex[:6]}")
    db.session.commit()

    reloaded = ProductRepository(db.session).find_by_id(product.id)
    assert reloaded.price_display_mode is None
    assert reloaded.to_dict()["price_display_mode"] is None


def test_override_persists(db):
    product = _product(db, f"netto-{uuid4().hex[:6]}", price_display_mode="netto")
    db.session.commit()

    reloaded = ProductRepository(db.session).find_by_id(product.id)
    assert reloaded.price_display_mode == "netto"
    assert reloaded.to_dict()["price_display_mode"] == "netto"


def test_migration_up_down_up(db):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    plugin_root = Path(__file__).resolve().parents[2]
    migration_path = (
        plugin_root / "migrations/versions/20260612_shop_product_display_mode.py"
    )
    spec = importlib.util.spec_from_file_location(
        "shop_product_display_mode", migration_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    connection = db.session.connection()
    context = MigrationContext.configure(connection)
    table = "shop_product"
    column = "price_display_mode"

    def columns():
        return {col["name"] for col in inspect(connection).get_columns(table)}

    with Operations.context(context):
        # create_all() already added the column via the model; drop it first so
        # the migration's upgrade is what (re)adds it in this test.
        module.downgrade()
        assert column not in columns()

        module.upgrade()
        assert column in columns()

        module.downgrade()
        assert column not in columns()

        # Restore so create_all/drop_all stay symmetric across the session.
        module.upgrade()
        assert column in columns()
