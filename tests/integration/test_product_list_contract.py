"""Catalogue list wire contract — shop products migrated to the agnostic seam.

``docs/architecture/catalogue-list-contract.md`` §2/§3/§4. The shop catalogue
list now speaks the contract:

- envelope is ``{items, total, page, per_page, pages}`` (``products`` is gone);
- ``total`` reflects the EFFECTIVE filter (search/category/tags), not the whole
  active catalogue, so pagination is correct for filtered results;
- each item carries ``id, slug, name, tags`` (empty array when none) plus its
  existing ``pricing`` block;
- ``q`` is the search param; ``tags`` is a CSV AND-filter riding the core tags
  port;
- ``GET /shop/filters`` returns the facet descriptor (category select + tags
  chips), and ``GET /shop/tags`` feeds the tag chips options.
"""
from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def _make_product(db, name, price="10.00", is_active=True):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid4().hex[:8]}",
        price=Decimal(price),
        is_active=is_active,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _tag(app, product_id, slugs):
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "shop_product", product_id, slugs
        )


def test_envelope_is_the_contract_shape(db, client):
    product = _make_product(db, "EnvelopeWidget")

    body = client.get("/api/v1/shop/products").get_json()

    assert set(body.keys()) == {"items", "total", "page", "per_page", "pages"}
    assert "products" not in body
    assert body["pages"] >= 1
    listed = next(item for item in body["items"] if item["slug"] == product.slug)
    assert listed["id"] == str(product.id)
    assert listed["name"] == "EnvelopeWidget"
    assert listed["tags"] == []
    assert "pricing" in listed


def test_empty_result_is_one_page(db, client):
    body = client.get("/api/v1/shop/products?q=nothing-matches-this-xyzzy").get_json()

    assert body["items"] == []
    assert body["total"] == 0
    assert body["pages"] == 1


def test_search_param_q_filters_and_total_reflects_filter(db, client):
    match = _make_product(db, "UniqueSearchableAardvark")
    _make_product(db, "OtherThing")

    body = client.get("/api/v1/shop/products?q=Aardvark").get_json()

    slugs = {item["slug"] for item in body["items"]}
    assert match.slug in slugs
    assert body["total"] == 1  # effective filter, not the whole catalogue


def test_tags_csv_and_semantics(db, client, app):
    both = _make_product(db, "BothTags")
    only_one = _make_product(db, "OnlyOneTag")
    _tag(app, both.id, ["red", "sale"])
    _tag(app, only_one.id, ["red"])

    body = client.get("/api/v1/shop/products?tags=red,sale").get_json()

    slugs = {item["slug"] for item in body["items"]}
    assert both.slug in slugs
    assert only_one.slug not in slugs
    assert body["total"] == 1
    listed = next(item for item in body["items"] if item["slug"] == both.slug)
    assert set(listed["tags"]) == {"red", "sale"}


def test_filters_descriptor_shape(db, client):
    body = client.get("/api/v1/shop/filters").get_json()

    facets = {facet["key"]: facet for facet in body["facets"]}
    assert facets["category"]["control"] == "select"
    assert facets["category"]["options_endpoint"] == "/api/v1/shop/categories"
    assert facets["tags"]["control"] == "chips"
    assert facets["tags"]["multi"] is True
    assert facets["tags"]["and"] is True
    assert facets["tags"]["options_endpoint"] == "/api/v1/shop/tags"


def test_tags_options_endpoint_offers_used_tags_only(db, client, app):
    product = _make_product(db, "TaggedForOptions")
    _tag(app, product.id, ["clearance"])

    body = client.get("/api/v1/shop/tags").get_json()

    slugs = {tag["slug"] for tag in body["tags"]}
    assert "clearance" in slugs
