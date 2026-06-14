"""S77 — the public product detail serializer appends tags + custom fields.

The fe-user product card reads the ``tags`` / ``custom_fields`` keys (plus the
``custom_field_defs`` for labels + type formatting) straight off the payload, so
``GET /shop/products/<slug>`` must surface them. Opt-in via the core helper — no
model import, no extra round trip on the card.
"""
from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.fixture
def client(app):
    return app.test_client()


def _make_product(db):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="TaggedWidget",
        slug=f"tagged-widget-{uuid4().hex[:8]}",
        price=Decimal("10.00"),
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def test_detail_exposes_empty_tags_and_custom_fields_by_default(db, client):
    product = _make_product(db)

    body = client.get(f"/api/v1/shop/products/{product.slug}").get_json()

    assert body["product"]["tags"] == []
    assert body["product"]["custom_fields"] == {}
    assert "custom_field_defs" in body["product"]


def test_detail_exposes_attached_tags_and_custom_fields(app, db, client):
    product = _make_product(db)

    with app.app_context():
        port = app.container.tags_and_custom_fields()
        port.set_tags("shop_product", product.id, ["featured"])

    body = client.get(f"/api/v1/shop/products/{product.slug}").get_json()

    assert body["product"]["tags"] == ["featured"]
