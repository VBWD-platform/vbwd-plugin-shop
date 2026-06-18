"""ShopProductSearchProvider — search hits + get_detail over real rows.

Exercises the cross-entity search seam contributed by shop: a query finds
ACTIVE products by name/description, the hit carries the public
``/shop/product/<slug>`` url + a price string, and ``get_detail`` re-resolves by
slug.
"""
from uuid import uuid4

import pytest

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.search_provider import ShopProductSearchProvider


def _make_product(db, *, name, slug, description="", price=19.99, is_active=True):
    product = Product(
        id=uuid4(),
        name=name,
        slug=slug,
        description=description,
        price=price,
        is_active=is_active,
    )
    db.session.add(product)
    db.session.commit()
    return product


@pytest.fixture
def provider():
    return ShopProductSearchProvider()


def test_search_finds_active_product_by_name(db, provider):
    _make_product(
        db,
        name="Blue Cotton Shirt",
        slug="blue-cotton-shirt",
        description="A comfy blue shirt.",
        price=19.99,
    )

    hits = provider.search("blue", limit=5)

    assert len(hits) == 1
    hit = hits[0]
    assert hit.entity_type == "shop_product"
    assert hit.entity_label == "Shop"
    assert hit.key == "blue-cotton-shirt"
    assert hit.title == "Blue Cotton Shirt"
    assert hit.url == "/shop/product/blue-cotton-shirt"
    assert hit.price is not None and "19.99" in hit.price


def test_search_blank_query_returns_empty(db, provider):
    _make_product(db, name="Anything", slug="anything")

    assert provider.search("   ", limit=5) == []


def test_get_detail_resolves_by_slug(db, provider):
    _make_product(
        db,
        name="Red Hat",
        slug="red-hat",
        description="A warm red hat.",
        price=9.5,
    )

    hit = provider.get_detail("red-hat")

    assert hit is not None
    assert hit.title == "Red Hat"
    assert hit.snippet == "A warm red hat."
    assert hit.url == "/shop/product/red-hat"


def test_get_detail_unknown_slug_returns_none(db, provider):
    assert provider.get_detail("does-not-exist") is None
