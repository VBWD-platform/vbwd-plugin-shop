"""S64: shop catalog exchangers — categories + products linked by slug.

These exercise the two S64 deltas to ``shop_exchangers.py``:

* a **new** ``shop_product_categories`` exchanger (``ProductCategory``), keyed by
  ``slug``, hierarchical via a ``parent_slug`` that resolves on import (the
  ``parent_id`` FK is export-only on the base, so a subclass resolves slug→id).
* an **upgraded** ``shop_products`` exchanger that carries its categories by
  ``category_slugs`` (the product↔category link is M2M) plus nested ``variants``
  and ``images`` (URLs only), resolved/recreated on import.

The product↔category link is **M2M** (``shop_product_category_link``), so the
serialised shape is ``category_slugs`` (a list). ``fk_natural_key_map`` only
serialises on export — it never resolves slug→id — so the link resolution lives
in the products subclass (skip-with-error when a referent slug is absent).

Data is seeded through the ORM session (no raw SQL); the shared ``db`` fixture
(``plugins/shop/tests/conftest.py``) creates + drops the test DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI, schema via Alembic, no raw SQL); SOLID (one exchanger per entity,
narrow ports); DI (session injected); DRY (reuse ``BaseModelExchanger``); Liskov
(unknown slug → error row, never crash; category parent resolves like the CMS
term parent); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin shop --full``.
"""
import uuid

from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import CLUSTER_SALES, ExportSelector
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory
from plugins.shop.shop.models.product_image import ProductImage
from plugins.shop.shop.models.product_variant import ProductVariant
from plugins.shop.shop.services.data_exchange.shop_exchangers import (
    build_shop_exchangers,
)


def _exchangers(session):
    return {
        exchanger.entity_key: exchanger for exchanger in build_shop_exchangers(session)
    }


def _unique(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestCategoryExchanger:
    def test_round_trip_by_slug(self, db):
        slug = _unique("cat")
        db.session.add(ProductCategory(name="Tools", slug=slug, sort_order=3))
        db.session.commit()

        exchanger = _exchangers(db.session)["shop_product_categories"]
        assert exchanger.cluster == CLUSTER_SALES
        rows = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert rows and rows[0]["slug"] == slug
        assert rows[0]["name"] == "Tools"
        assert rows[0]["sort_order"] == 3

        db.session.query(ProductCategory).filter(ProductCategory.slug == slug).delete()
        db.session.commit()

        payload = build_envelope("shop_product_categories", rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1

        rebuilt = (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == slug)
            .first()
        )
        assert rebuilt is not None
        assert rebuilt.name == "Tools"
        assert rebuilt.sort_order == 3

    def test_parent_link_by_slug(self, db):
        parent_slug = _unique("parent")
        child_slug = _unique("child")
        parent = ProductCategory(name="Parent", slug=parent_slug)
        db.session.add(parent)
        db.session.commit()
        db.session.add(
            ProductCategory(name="Child", slug=child_slug, parent_id=parent.id)
        )
        db.session.commit()

        exchanger = _exchangers(db.session)["shop_product_categories"]
        rows = exchanger.export(
            ExportSelector(ids=[child_slug]), include_pii=False
        ).rows
        assert rows[0]["parent_slug"] == parent_slug
        assert "parent_id" not in rows[0]

        db.session.query(ProductCategory).filter(
            ProductCategory.slug == child_slug
        ).delete()
        db.session.commit()

        payload = build_envelope("shop_product_categories", rows, instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)

        rebuilt = (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == child_slug)
            .first()
        )
        assert rebuilt is not None
        assert rebuilt.parent_id == parent.id

    def test_unknown_parent_slug_is_error_row(self, db):
        slug = _unique("orphan")
        exchanger = _exchangers(db.session)["shop_product_categories"]
        rows = [{"slug": slug, "name": "Orphan", "parent_slug": "does-not-exist"}]
        payload = build_envelope("shop_product_categories", rows, instance="test")

        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.errors
        assert result.created == 0
        assert (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == slug)
            .first()
            is None
        )


class TestProductCategoryLink:
    def _seed_product_in_category(self, db):
        cat_slug = _unique("cat")
        prod_slug = _unique("prod")
        category = ProductCategory(name="Gear", slug=cat_slug)
        db.session.add(category)
        db.session.commit()
        product = Product(
            name="Hammer",
            slug=prod_slug,
            sku=_unique("SKU"),
            price=19,
            is_digital=False,
            dimensions={"length": 30, "width": 5},
        )
        product.categories.append(category)
        db.session.add(product)
        db.session.commit()
        return cat_slug, prod_slug

    def test_product_carries_category_slugs(self, db):
        cat_slug, prod_slug = self._seed_product_in_category(db)
        exchanger = _exchangers(db.session)["shop_products"]
        rows = exchanger.export(ExportSelector(ids=[prod_slug]), include_pii=False).rows
        assert rows[0]["category_slugs"] == [cat_slug]

    def test_round_trip_links_product_to_category_by_slug(self, db):
        cat_slug, prod_slug = self._seed_product_in_category(db)
        exchanger = _exchangers(db.session)["shop_products"]
        rows = exchanger.export(ExportSelector(ids=[prod_slug]), include_pii=False).rows

        db.session.query(Product).filter(Product.slug == prod_slug).delete()
        db.session.commit()

        payload = build_envelope("shop_products", rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1

        rebuilt = db.session.query(Product).filter(Product.slug == prod_slug).first()
        assert rebuilt is not None
        assert rebuilt.price == 19.0
        assert rebuilt.is_digital is False
        assert rebuilt.dimensions == {"length": 30, "width": 5}
        assert [c.slug for c in rebuilt.categories] == [cat_slug]

    def test_unknown_category_slug_is_error_row(self, db):
        prod_slug = _unique("prod")
        exchanger = _exchangers(db.session)["shop_products"]
        rows = [
            {
                "slug": prod_slug,
                "name": "Orphan",
                "price": 5,
                "category_slugs": ["missing-cat"],
            }
        ]
        payload = build_envelope("shop_products", rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.errors
        assert result.created == 0
        assert (
            db.session.query(Product).filter(Product.slug == prod_slug).first() is None
        )


class TestProductVariantsAndImages:
    def _seed_full_product(self, db):
        prod_slug = _unique("prod")
        product = Product(
            name="Boots",
            slug=prod_slug,
            sku=_unique("SKU"),
            price=49,
            has_variants=True,
        )
        product.variants.append(
            ProductVariant(name="42", sku=_unique("V"), price=49, sort_order=0)
        )
        product.variants.append(
            ProductVariant(name="43", sku=_unique("V"), price=49, sort_order=1)
        )
        product.images.append(
            ProductImage(url="https://x/1.jpg", alt="front", sort_order=0)
        )
        product.images.append(
            ProductImage(url="https://x/2.jpg", alt="back", sort_order=1)
        )
        db.session.add(product)
        db.session.commit()
        return prod_slug

    def test_round_trip_recreates_variants_and_images(self, db):
        prod_slug = self._seed_full_product(db)
        exchanger = _exchangers(db.session)["shop_products"]
        rows = exchanger.export(ExportSelector(ids=[prod_slug]), include_pii=False).rows
        assert len(rows[0]["variants"]) == 2
        assert len(rows[0]["images"]) == 2
        assert rows[0]["images"][0]["url"] == "https://x/1.jpg"

        db.session.query(Product).filter(Product.slug == prod_slug).delete()
        db.session.commit()

        payload = build_envelope("shop_products", rows, instance="test")
        exchanger.import_(payload, mode="upsert", dry_run=False)

        rebuilt = db.session.query(Product).filter(Product.slug == prod_slug).first()
        assert {v.name for v in rebuilt.variants} == {"42", "43"}
        assert {img.url for img in rebuilt.images} == {
            "https://x/1.jpg",
            "https://x/2.jpg",
        }

    def test_reimport_replaces_children_without_duplicates(self, db):
        prod_slug = self._seed_full_product(db)
        exchanger = _exchangers(db.session)["shop_products"]
        rows = exchanger.export(ExportSelector(ids=[prod_slug]), include_pii=False).rows

        # Re-import the same envelope onto the existing product (upsert by slug).
        payload = build_envelope("shop_products", rows, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.updated == 1

        rebuilt = db.session.query(Product).filter(Product.slug == prod_slug).first()
        assert len(rebuilt.variants) == 2
        assert len(rebuilt.images) == 2


class TestDryRunAndManifest:
    def test_dry_run_does_not_write(self, db):
        slug = _unique("cat")
        exchanger = _exchangers(db.session)["shop_product_categories"]
        rows = [{"slug": slug, "name": "Preview"}]
        payload = build_envelope("shop_product_categories", rows, instance="test")

        result = exchanger.import_(payload, mode="upsert", dry_run=True)
        assert result.created == 1
        assert (
            db.session.query(ProductCategory)
            .filter(ProductCategory.slug == slug)
            .first()
            is None
        )

    def test_exchangers_have_shop_perms(self, db):
        exchangers = _exchangers(db.session)
        category = exchangers["shop_product_categories"]
        product = exchangers["shop_products"]
        assert category.export_permission == "shop.products.view"
        assert category.import_permission == "shop.categories.manage"
        assert product.export_permission == "shop.products.view"
        assert product.import_permission == "shop.products.manage"

    def test_registration_includes_catalog_keys(self, db):
        from vbwd.services.data_exchange.registry import data_exchange_registry
        from plugins.shop import ShopPlugin

        plugin = ShopPlugin()
        plugin.initialize({})
        plugin._register_data_exchangers()

        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in data_exchange_registry.all()
        }
        for key in ("shop_products", "shop_product_categories"):
            assert key in by_key
            assert by_key[key].cluster == CLUSTER_SALES
