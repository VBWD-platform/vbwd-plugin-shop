"""S154 D7 — the public product / category detail carries ``seo_indexable``.

Both frontends render a product or category page ``noindex,follow`` when its
fe-admin switch is off, so the public detail payload exposes the effective
switch: ``product.seo_indexable`` follows ``seo_index_products`` (default on),
``category.seo_indexable`` follows ``seo_index_categories`` (default off). The
payloads are otherwise unchanged.

Seeded through repositories; config through the live ``config_store`` and
restored afterwards.

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY (one switch reader, ``seo_indexing_enabled``) · Liskov · clean code ·
NO OVERENGINEERING. Guard: ``bin/pre-commit-check.sh --plugin shop --full``.
"""
from uuid import uuid4

import pytest
from flask import current_app

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory
from plugins.shop.shop.repositories.product_category_repository import (
    ProductCategoryRepository,
)
from plugins.shop.shop.repositories.product_repository import ProductRepository
from plugins.shop.shop.services.plugin_config import (
    SEO_INDEX_CATEGORIES_KEY,
    SEO_INDEX_PRODUCTS_KEY,
)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def shop_switches(db):
    """Save shop switch values for one test; restore the saved blob after."""
    store = current_app.config_store
    saved = dict(store.get_config("shop") or {})
    store.save_config(
        "shop",
        {
            key: value
            for key, value in saved.items()
            if key not in (SEO_INDEX_PRODUCTS_KEY, SEO_INDEX_CATEGORIES_KEY)
        },
    )

    def save(**values):
        store.save_config("shop", {**(store.get_config("shop") or {}), **values})

    yield save
    store.save_config("shop", saved)


def _seed_product(db):
    slug = f"d7-product-{uuid4().hex[:10]}"
    return ProductRepository(db.session).save(
        Product(id=uuid4(), name=slug, slug=slug, price=9.5, is_active=True)
    )


def _seed_category(db):
    slug = f"d7-category-{uuid4().hex[:10]}"
    return ProductCategoryRepository(db.session).save(
        ProductCategory(id=uuid4(), name=slug, slug=slug)
    )


def _product(client, product):
    return client.get(f"/api/v1/shop/products/{product.slug}").get_json()["product"]


def _category(client, category):
    response = client.get(f"/api/v1/shop/categories/{category.slug}")
    return response.get_json()["category"]


def test_product_is_indexable_by_default(db, client, shop_switches):
    product = _seed_product(db)

    payload = _product(client, product)

    assert payload["seo_indexable"] is True
    assert payload["slug"] == product.slug


def test_product_follows_its_switch(db, client, shop_switches):
    product = _seed_product(db)
    shop_switches(**{SEO_INDEX_PRODUCTS_KEY: False})

    assert _product(client, product)["seo_indexable"] is False


def test_category_is_not_indexable_by_default(db, client, shop_switches):
    category = _seed_category(db)

    payload = _category(client, category)

    assert payload["seo_indexable"] is False
    assert payload["slug"] == category.slug


def test_category_follows_its_switch(db, client, shop_switches):
    category = _seed_category(db)
    shop_switches(**{SEO_INDEX_CATEGORIES_KEY: True})

    assert _category(client, category)["seo_indexable"] is True
