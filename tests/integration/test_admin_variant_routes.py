"""S101.0 — admin variant CRUD API (integration).

Contract:
- create → list → update → reorder → toggle → delete via the admin routes.
- variant pricing flows through the ``PriceFactory`` (a ``pricing`` block is
  returned, computed from the variant's price + the product's taxes).
- ``shop.products.manage`` gates the mutations.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.tax import Tax


@pytest.fixture
def client(app):
    return app.test_client()


HEADERS = {"Authorization": "Bearer valid"}


def _make_admin(db):
    admin = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.ADMIN,
    )
    db.session.add(admin)
    db.session.commit()
    return admin


def _make_product(db, *, with_tax=True):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="Ibuprofen 400mg",
        slug=f"ibuprofen-{uuid4().hex[:8]}",
        price=4.00,
        is_active=True,
    )
    if with_tax:
        tax = Tax(
            id=uuid4(),
            name="Reduced",
            code=f"RED_{uuid4().hex[:6]}",
            rate=Decimal("7.00"),
            is_active=True,
        )
        db.session.add(tax)
        product.taxes = [tax]
    db.session.add(product)
    db.session.commit()
    return product


def _auth_as_admin(monkeypatch, admin):
    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    monkeypatch.setattr(type(admin), "has_permission", lambda self, perm: True)


def test_variant_crud_lifecycle(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    _auth_as_admin(monkeypatch, admin)
    base = f"/api/v1/admin/shop/products/{product.id}/variants"

    # CREATE two
    first = client.post(
        base,
        json={"name": "Pack of 20", "sku": f"PZN-{uuid4().hex[:6]}", "price": 4.99},
        headers=HEADERS,
    )
    assert first.status_code == 201, first.get_json()
    first_id = first.get_json()["variant"]["id"]
    # Pricing computed via the factory (variant price 4.99 + product 7% tax).
    assert "pricing" in first.get_json()["variant"]

    second = client.post(
        base,
        json={"name": "Pack of 50", "sku": f"PZN-{uuid4().hex[:6]}", "price": 9.99},
        headers=HEADERS,
    )
    assert second.status_code == 201
    second_id = second.get_json()["variant"]["id"]

    # LIST
    listing = client.get(base, headers=HEADERS)
    assert listing.status_code == 200
    assert len(listing.get_json()["variants"]) == 2

    # UPDATE
    updated = client.put(
        f"{base}/{first_id}", json={"name": "Pack of 20 tablets"}, headers=HEADERS
    )
    assert updated.status_code == 200
    assert updated.get_json()["variant"]["name"] == "Pack of 20 tablets"

    # REORDER (second first)
    reorder = client.post(
        f"{base}/reorder",
        json={"variant_ids": [second_id, first_id]},
        headers=HEADERS,
    )
    assert reorder.status_code == 200
    order = [v["id"] for v in reorder.get_json()["variants"]]
    assert order == [second_id, first_id]

    # TOGGLE
    toggled = client.post(f"{base}/{first_id}/toggle", headers=HEADERS)
    assert toggled.status_code == 200
    assert toggled.get_json()["variant"]["is_active"] is False

    # DELETE
    deleted = client.delete(f"{base}/{first_id}", headers=HEADERS)
    assert deleted.status_code == 200
    remaining = client.get(base, headers=HEADERS)
    assert len(remaining.get_json()["variants"]) == 1


def test_create_variant_rejects_duplicate_sku(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    _auth_as_admin(monkeypatch, admin)
    base = f"/api/v1/admin/shop/products/{product.id}/variants"
    sku = f"PZN-{uuid4().hex[:6]}"

    assert (
        client.post(
            base, json={"name": "A", "sku": sku, "price": 1.0}, headers=HEADERS
        ).status_code
        == 201
    )
    dup = client.post(
        base, json={"name": "B", "sku": sku, "price": 1.0}, headers=HEADERS
    )
    assert dup.status_code == 400


def test_variant_routes_404_for_unknown_product(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    resp = client.get(
        f"/api/v1/admin/shop/products/{uuid4()}/variants", headers=HEADERS
    )
    assert resp.status_code == 404
