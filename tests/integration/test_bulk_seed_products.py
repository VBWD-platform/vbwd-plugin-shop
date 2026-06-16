"""Integration: S89.1 load-test bulk seed for ``shop_products`` (real PG).

Proves the seed override end-to-end through the repository layer (no raw SQL):

* ``bulk_seed(10)`` inserts 10 valid ``loadtest-`` products, each linked to the
  one shared ``loadtest-`` category, all priced.
* the seeded rows round-trip: export → wipe → import recreates them with the
  category link intact (the S89 measurement's hard requirement).
* ``bulk_seed`` is idempotent (a second run skips, the category is reused).
* ``bulk_seed(reset=True)`` drops only the ``loadtest-`` rows + the now-orphaned
  ``loadtest-`` category, leaving a pre-existing non-``loadtest-`` product and
  its category untouched.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin shop
--full``.
"""
from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import ExportSelector

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory
from plugins.shop.shop.services.data_exchange.shop_exchangers import (
    build_shop_exchangers,
)

_SEED_CATEGORY_SLUG = "loadtest-shop_products-cat"


def _products_exchanger(session):
    return {
        exchanger.entity_key: exchanger for exchanger in build_shop_exchangers(session)
    }["shop_products"]


def _loadtest_products(session):
    return session.query(Product).filter(Product.slug.like("loadtest-%")).all()


class TestBulkSeedProducts:
    def test_seeds_valid_linked_rows(self, db):
        exchanger = _products_exchanger(db.session)

        result = exchanger.bulk_seed(10)
        db.session.commit()

        assert result.created == 10
        products = _loadtest_products(db.session)
        assert len(products) == 10
        for product in products:
            assert product.price == exchanger._SEED_PRODUCT_PRICE
            assert [category.slug for category in product.categories] == [
                _SEED_CATEGORY_SLUG
            ]

    def test_round_trips_with_category_link(self, db):
        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(10)
        db.session.commit()

        exported = exchanger.export(ExportSelector(ids=None), include_pii=False).rows
        loadtest_rows = [row for row in exported if row["slug"].startswith("loadtest-")]
        assert len(loadtest_rows) == 10
        assert all(
            row["category_slugs"] == [_SEED_CATEGORY_SLUG] for row in loadtest_rows
        )

        # Wipe the products (the category stays) and re-import the envelope.
        db.session.query(Product).filter(Product.slug.like("loadtest-%")).delete(
            synchronize_session=False
        )
        db.session.commit()

        payload = build_envelope("shop_products", loadtest_rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)

        assert result.created == 10
        rebuilt = _loadtest_products(db.session)
        assert len(rebuilt) == 10
        assert all(
            [category.slug for category in product.categories] == [_SEED_CATEGORY_SLUG]
            for product in rebuilt
        )

    def test_idempotent(self, db):
        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(10)
        db.session.commit()

        # A fresh exchanger (cleared cache) must reuse the existing category.
        exchanger = _products_exchanger(db.session)
        result = exchanger.bulk_seed(10)
        db.session.commit()

        assert result.created == 0
        assert result.skipped == 10
        assert len(_loadtest_products(db.session)) == 10
        categories = (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == _SEED_CATEGORY_SLUG)
            .all()
        )
        assert len(categories) == 1

    def test_round_trips_after_reset_drops_shared_category(self, db):
        """Reproduce the S89 bench: reset deletes the shared category, then the
        exported envelope is re-imported. The load-test category slug in each
        row must be self-healed (recreated) so all rows import, not skipped.
        """
        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(10)
        db.session.commit()

        exported = exchanger.export(ExportSelector(ids=None), include_pii=False).rows
        loadtest_rows = [row for row in exported if row["slug"].startswith("loadtest-")]
        assert len(loadtest_rows) == 10

        # Reset to empty: this drops the load-test products AND the now-orphaned
        # shared ``loadtest-`` category (the production sequence the bench runs
        # before every ``import:cold``).
        reset_exchanger = _products_exchanger(db.session)
        reset_exchanger.bulk_seed(0, reset=True)
        db.session.commit()
        assert (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == _SEED_CATEGORY_SLUG)
            .first()
            is None
        )

        payload = build_envelope("shop_products", loadtest_rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)

        assert result.errors == []
        assert result.created == 10
        rebuilt = _loadtest_products(db.session)
        assert len(rebuilt) == 10
        assert all(
            [category.slug for category in product.categories] == [_SEED_CATEGORY_SLUG]
            for product in rebuilt
        )

        # A follow-up export returns the re-imported rows (the bench's next
        # ``export:api`` surface would otherwise see only demo rows → empty).
        re_exported = exchanger.export(ExportSelector(ids=None), include_pii=False).rows
        assert (
            len([row for row in re_exported if row["slug"].startswith("loadtest-")])
            == 10
        )

    def test_import_unknown_non_seed_category_still_skips_with_error(self, db):
        """Guard against an over-broad fix: a genuinely unknown (non-seed)
        category slug must still skip-with-error, never auto-create a category.
        """
        exchanger = _products_exchanger(db.session)
        payload = build_envelope(
            "shop_products",
            [
                {
                    "slug": "manual-product",
                    "name": "Manual",
                    "price": 5.0,
                    "category_slugs": ["definitely-not-a-real-category"],
                }
            ],
            instance="test",
        )

        result = exchanger.import_(payload, mode="upsert", dry_run=False)

        assert result.created == 0
        assert len(result.errors) == 1
        assert "definitely-not-a-real-category" in result.errors[0]["reason"]
        assert (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == "definitely-not-a-real-category")
            .first()
            is None
        )

    def test_reset_drops_only_loadtest_rows_and_orphaned_category(self, db):
        # A pre-existing real product + real category must survive --reset.
        keeper_category = ProductCategory(slug="real-cat", name="Real")
        db.session.add(keeper_category)
        keeper = Product(slug="real-product", name="Real", price=5.0)
        keeper.categories = [keeper_category]
        db.session.add(keeper)
        db.session.commit()

        exchanger = _products_exchanger(db.session)
        exchanger.bulk_seed(10)
        db.session.commit()

        exchanger = _products_exchanger(db.session)
        result = exchanger.bulk_seed(5, reset=True)
        db.session.commit()

        assert result.deleted == 10
        assert result.created == 5
        assert len(_loadtest_products(db.session)) == 5

        # The real product + its category are untouched.
        assert (
            db.session.query(Product).filter(Product.slug == "real-product").first()
            is not None
        )
        assert (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == "real-cat")
            .first()
            is not None
        )
