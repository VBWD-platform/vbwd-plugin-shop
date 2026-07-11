"""S72.4 follow-up — the public product LIST exposes the same ``pricing`` block
as the detail route (integration).

Contract:
- ``GET /shop/products`` returns the catalogue envelope ``{"items": [...]}``
  (wire contract) where each product carries a ``pricing`` block identical in
  shape/values to the detail route's block for the same product (net/gross +
  ``effective_display_mode`` + ``prices_display_mode``).
- The detail route is unchanged (characterization: the block it returns equals the
  one now produced by the shared helper).
- A product with a ``netto`` override surfaces ``effective_display_mode == "netto"``
  in the LIST too.
"""
from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def _make_product(db, price_display_mode=None):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="ListWidget",
        slug=f"list-widget-{uuid4().hex[:8]}",
        price=Decimal("100.00"),
        is_active=True,
        price_display_mode=price_display_mode,
    )
    db.session.add(product)
    db.session.commit()
    return product


def test_list_products_each_item_has_pricing_block(db, client):
    product = _make_product(db, price_display_mode=None)

    resp = client.get("/api/v1/shop/products")

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert "items" in body
    listed = next(p for p in body["items"] if p["slug"] == product.slug)
    pricing = listed["pricing"]
    assert pricing["prices_display_mode"] == "brutto"
    assert pricing["effective_display_mode"] == "brutto"
    assert pricing["net_amount"] == "100.00"
    assert pricing["gross_amount"] == "100.00"


def test_list_pricing_matches_detail_block(db, client):
    product = _make_product(db, price_display_mode=None)

    list_resp = client.get("/api/v1/shop/products")
    detail_resp = client.get(f"/api/v1/shop/products/{product.slug}")

    assert list_resp.status_code == 200
    assert detail_resp.status_code == 200

    listed = next(p for p in list_resp.get_json()["items"] if p["slug"] == product.slug)
    detail = detail_resp.get_json()["product"]
    assert listed["pricing"] == detail["pricing"]


def test_list_netto_override_surfaces_effective_netto(db, client):
    product = _make_product(db, price_display_mode="netto")

    resp = client.get("/api/v1/shop/products")

    assert resp.status_code == 200, resp.get_json()
    listed = next(p for p in resp.get_json()["items"] if p["slug"] == product.slug)
    pricing = listed["pricing"]
    assert pricing["prices_display_mode"] == "brutto"
    assert pricing["effective_display_mode"] == "netto"
