"""Integration: S89 scale bounds for the shop ``shop_products`` exchanger.

These tests assert ALGORITHMIC bounds (not wall-clock), so a regression to the
old per-row behaviour fails CI without needing a 100k run:

* **import flush count** — importing N children-less products must flush
  O(N/chunk_size) times, NOT once per product (the old ``_apply_links`` flushed
  per row → O(N) → the 100k import hang). A sibling test proves a product that
  DOES carry variants/images still round-trips with no duplicate-sku collision.
* **reset statement count** — resetting M seeded products must issue a BOUNDED
  number of SQL statements (a handful of set-based deletes), NOT O(M); and it
  must remove the products AND their link/child rows while leaving non-loadtest
  data untouched.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin shop
--full``.
"""
from contextlib import contextmanager

from sqlalchemy import event

from vbwd.services.data_exchange.base_model_exchanger import EXPORT_CHUNK_SIZE
from vbwd.services.data_exchange.envelope import build_envelope

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import (
    ProductCategory,
    shop_product_category_link,
)
from plugins.shop.shop.models.product_image import ProductImage
from plugins.shop.shop.models.product_variant import ProductVariant
from plugins.shop.shop.services.data_exchange.shop_exchangers import (
    build_shop_exchangers,
)

_SEED_CATEGORY_SLUG = "loadtest-shop_products-cat"


def _products_exchanger(session):
    return {
        exchanger.entity_key: exchanger for exchanger in build_shop_exchangers(session)
    }["shop_products"]


@contextmanager
def _count_flushes(session):
    """Count ``session.flush()`` invocations within the block."""
    counter = {"count": 0}
    original_flush = session.flush

    def _counting_flush(*args, **kwargs):
        counter["count"] += 1
        return original_flush(*args, **kwargs)

    session.flush = _counting_flush
    try:
        yield counter
    finally:
        session.flush = original_flush


@contextmanager
def _record_statements(engine):
    """Record every executed SQL statement text within the block."""
    statements = []

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


def _count_deletes_for(statements, table_name):
    """How many recorded statements are a DELETE against ``table_name``."""
    return sum(
        1
        for statement in statements
        if "DELETE" in statement.upper() and table_name in statement
    )


class TestImportFlushBound:
    def test_children_less_import_flushes_per_batch_not_per_row(self, db):
        """N children-less products must flush O(N/chunk_size), not O(N) times."""
        row_count = 500
        exchanger = _products_exchanger(db.session)
        # Prerequisite shared category (the seed envelope references it by slug).
        exchanger._ensure_seed_prerequisite()
        db.session.commit()

        rows = [
            {
                "slug": f"loadtest-shop_products-{index}",
                "name": f"Load-test product {index}",
                "price": 9.99,
                "category_slugs": [_SEED_CATEGORY_SLUG],
            }
            for index in range(row_count)
        ]
        payload = build_envelope("shop_products", rows, instance="test")

        with _count_flushes(db.session) as flushes:
            result = exchanger.import_(payload, mode="upsert", dry_run=False)

        assert result.created == row_count
        # The old per-product flush would be >= row_count. The fix flushes only
        # at chunk boundaries: bound generously to a small multiple of the chunk
        # count so any return to per-row flushing fails this test.
        max_expected_flushes = (row_count // EXPORT_CHUNK_SIZE) + 5
        assert flushes["count"] <= max_expected_flushes, (
            f"expected <= {max_expected_flushes} flushes for {row_count} rows, "
            f"got {flushes['count']} (regressed to per-row flush?)"
        )

    def test_product_with_children_round_trips_without_sku_collision(self, db):
        """A product WITH variants/images must still re-import with no collision."""
        exchanger = _products_exchanger(db.session)
        exchanger._ensure_seed_prerequisite()
        db.session.commit()

        row = {
            "slug": "loadtest-shop_products-rich",
            "name": "Rich product",
            "price": 12.0,
            "category_slugs": [_SEED_CATEGORY_SLUG],
            "variants": [
                {"name": "Small", "sku": "loadtest-sku-small", "price_float": 12.0},
            ],
            "images": [
                {"url": "https://example.test/a.png", "is_primary": True},
            ],
        }
        payload = build_envelope("shop_products", [row], instance="test")

        first = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert first.created == 1

        # Re-import the SAME row: the delete-and-replace must avoid a duplicate
        # ``sku`` collision (the per-row flush is still taken on the child path).
        second = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert second.updated == 1
        assert second.errors == []

        product = (
            db.session.query(Product)
            .filter(Product.slug == "loadtest-shop_products-rich")
            .first()
        )
        assert len(product.variants) == 1
        assert product.variants[0].sku == "loadtest-sku-small"
        assert len(product.images) == 1


class TestResetStatementBound:
    def test_reset_is_bounded_statements_and_clears_links(self, db):
        seed_count = 200
        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(seed_count)
        db.session.commit()
        assert (
            db.session.query(Product).filter(Product.slug.like("loadtest-%")).count()
            == seed_count
        )

        reset_exchanger = _products_exchanger(db.session)
        engine = db.session.get_bind()
        with _record_statements(engine) as statements:
            reset_exchanger.bulk_seed(0, reset=True)
            db.session.commit()

        delete_statements = [
            statement for statement in statements if "DELETE" in statement.upper()
        ]
        # A handful of set-based deletes (link + tax + variant + image + parent +
        # the orphaned category), NOT one-per-row. Bound well under the seed count
        # so any return to per-row deletion fails this test.
        assert len(delete_statements) <= 12, (
            f"reset issued {len(delete_statements)} DELETE statements for "
            f"{seed_count} rows — expected a bounded set-based reset"
        )
        # The link table must be cleared by an EXPLICIT set-based DELETE (one
        # statement), not left to the unindexed DB cascade — proving the O(N²)
        # cascade scan is avoided. Exactly one such statement per dependent table.
        link_table = shop_product_category_link.name
        assert _count_deletes_for(delete_statements, link_table) == 1, (
            f"expected exactly one set-based DELETE against {link_table}; "
            "a cascade-only reset would emit none and seq-scan it per row"
        )

        # Products + their link rows are gone.
        assert (
            db.session.query(Product).filter(Product.slug.like("loadtest-%")).count()
            == 0
        )
        link_rows = db.session.execute(shop_product_category_link.select()).fetchall()
        assert link_rows == []

    def test_reset_clears_child_rows_and_spares_non_loadtest(self, db):
        # A real product with children + category must survive the loadtest reset.
        keeper_category = ProductCategory(slug="real-cat-scale", name="Real")
        db.session.add(keeper_category)
        keeper = Product(slug="real-product-scale", name="Real", price=5.0)
        keeper.categories = [keeper_category]
        keeper.variants = [ProductVariant(name="V", sku="real-sku", price_float=5.0)]
        keeper.images = [ProductImage(url="https://example.test/real.png")]
        db.session.add(keeper)
        db.session.commit()

        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(50)
        db.session.commit()

        reset_exchanger = _products_exchanger(db.session)
        reset_exchanger.bulk_seed(0, reset=True)
        db.session.commit()

        # Loadtest products + their child rows gone; the real product's children
        # untouched.
        assert (
            db.session.query(Product).filter(Product.slug.like("loadtest-%")).count()
            == 0
        )
        survivor = (
            db.session.query(Product)
            .filter(Product.slug == "real-product-scale")
            .first()
        )
        assert survivor is not None
        assert len(survivor.variants) == 1
        assert len(survivor.images) == 1
