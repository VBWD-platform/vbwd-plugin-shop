"""S116.1 — product create/update accept a type + values; validation → 400.

Also proves a NULL-type product (base-only) saves with empty values, and product
serialisation includes the new fields.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from plugins.shop.shop.models.product_type import (
    PRODUCT_TYPE_SOURCE_ADMIN,
    ProductType,
)


@pytest.fixture
def client(app):
    return app.test_client()


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


def _seed_type(db, slug):
    product_type = ProductType(
        id=uuid4(),
        slug=slug,
        name="Class type",
        product_type_fields=[
            {
                "slug": "product_class",
                "type": "select",
                "label": "Class",
                "required": True,
                "options": ["RX", "OTC"],
            },
            {"slug": "strength", "type": "string", "label": "Strength"},
        ],
        source=PRODUCT_TYPE_SOURCE_ADMIN,
        is_active=True,
    )
    db.session.add(product_type)
    db.session.commit()
    return product_type


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


HEADERS = {"Authorization": "Bearer valid"}


def test_create_product_with_valid_type_values(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    type_slug = f"typed-{uuid4().hex[:8]}"
    _seed_type(db, type_slug)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Typed Widget",
            "price": "10.00",
            "product_type_slug": type_slug,
            "type_field_values": {"product_class": "RX", "strength": "500mg"},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.get_json()
    product = resp.get_json()["product"]
    assert product["product_type_slug"] == type_slug
    assert product["type_field_values"] == {"product_class": "RX", "strength": "500mg"}


def test_create_product_missing_required_type_value_is_400(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    type_slug = f"typed-{uuid4().hex[:8]}"
    _seed_type(db, type_slug)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Bad Widget",
            "price": "10.00",
            "product_type_slug": type_slug,
            "type_field_values": {"strength": "500mg"},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400, resp.get_json()


def test_create_product_unknown_type_is_400(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Ghost Type Widget",
            "price": "10.00",
            "product_type_slug": f"nope-{uuid4().hex[:8]}",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400, resp.get_json()


def test_create_base_product_without_type_saves_empty_values(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={"name": "Plain Widget", "price": "10.00"},
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.get_json()
    product = resp.get_json()["product"]
    assert product["product_type_slug"] is None
    assert product["type_field_values"] == {}


def test_update_product_assigns_type_and_values(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    type_slug = f"typed-{uuid4().hex[:8]}"
    _seed_type(db, type_slug)

    created = client.post(
        "/api/v1/admin/shop/products",
        json={"name": "Later Typed", "price": "5.00"},
        headers=HEADERS,
    )
    product_id = created.get_json()["product"]["id"]

    resp = client.put(
        f"/api/v1/admin/shop/products/{product_id}",
        json={
            "product_type_slug": type_slug,
            "type_field_values": {"product_class": "OTC"},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.get_json()
    product = resp.get_json()["product"]
    assert product["product_type_slug"] == type_slug
    assert product["type_field_values"] == {"product_class": "OTC"}


def test_update_product_invalid_value_is_400(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    type_slug = f"typed-{uuid4().hex[:8]}"
    _seed_type(db, type_slug)

    created = client.post(
        "/api/v1/admin/shop/products",
        json={"name": "Update Bad", "price": "5.00"},
        headers=HEADERS,
    )
    product_id = created.get_json()["product"]["id"]

    resp = client.put(
        f"/api/v1/admin/shop/products/{product_id}",
        json={
            "product_type_slug": type_slug,
            "type_field_values": {"product_class": "INVALID"},
        },
        headers=HEADERS,
    )
    assert resp.status_code == 400, resp.get_json()
