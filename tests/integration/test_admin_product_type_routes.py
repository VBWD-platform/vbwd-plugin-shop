"""S116.1 — admin product-type CRUD + read routes (integration).

Contract:
  - GET  /api/v1/shop/product-types            → active types (public read).
  - GET  /api/v1/shop/product-types/<slug>     → one resolved field set.
  - GET  /api/v1/admin/shop/product-types      → all types.
  - POST /api/v1/admin/shop/product-types      → create source='admin'.
  - PUT  /api/v1/admin/shop/product-types/<slug>    (plugin rows → 409).
  - DELETE /api/v1/admin/shop/product-types/<slug>  (plugin rows → 409).
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from plugins.shop.shop.models.product_type import (
    PRODUCT_TYPE_SOURCE_PLUGIN,
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


def test_admin_create_and_public_read_product_type(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    slug = f"cars-{uuid4().hex[:8]}"

    resp = client.post(
        "/api/v1/admin/shop/product-types",
        json={
            "slug": slug,
            "name": "Cars",
            "product_type_fields": [
                {"slug": "mileage", "type": "integer", "label": "Mileage"}
            ],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["product_type"]["source"] == "admin"

    detail = client.get(f"/api/v1/shop/product-types/{slug}")
    assert detail.status_code == 200
    assert detail.get_json()["product_type"]["slug"] == slug

    listing = client.get("/api/v1/shop/product-types")
    assert listing.status_code == 200
    slugs = [pt["slug"] for pt in listing.get_json()["product_types"]]
    assert slug in slugs


def test_admin_create_rejects_duplicate_slug(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    slug = f"dup-{uuid4().hex[:8]}"
    body = {"slug": slug, "name": "Dup"}

    assert (
        client.post(
            "/api/v1/admin/shop/product-types", json=body, headers=HEADERS
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/admin/shop/product-types", json=body, headers=HEADERS
        ).status_code
        == 400
    )


def test_admin_update_admin_type(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    slug = f"edit-{uuid4().hex[:8]}"
    client.post(
        "/api/v1/admin/shop/product-types",
        json={"slug": slug, "name": "Before"},
        headers=HEADERS,
    )

    resp = client.put(
        f"/api/v1/admin/shop/product-types/{slug}",
        json={"name": "After", "is_active": False},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product_type"]["name"] == "After"
    assert resp.get_json()["product_type"]["is_active"] is False


def test_plugin_type_is_read_only_on_update_and_delete(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    slug = f"plugintype-{uuid4().hex[:8]}"
    db.session.add(
        ProductType(
            id=uuid4(),
            slug=slug,
            name="Plugin",
            source=PRODUCT_TYPE_SOURCE_PLUGIN,
            is_active=True,
        )
    )
    db.session.commit()

    put_resp = client.put(
        f"/api/v1/admin/shop/product-types/{slug}",
        json={"name": "hax"},
        headers=HEADERS,
    )
    assert put_resp.status_code == 409

    del_resp = client.delete(
        f"/api/v1/admin/shop/product-types/{slug}", headers=HEADERS
    )
    assert del_resp.status_code == 409


def test_admin_delete_admin_type(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    slug = f"del-{uuid4().hex[:8]}"
    client.post(
        "/api/v1/admin/shop/product-types",
        json={"slug": slug, "name": "ToDelete"},
        headers=HEADERS,
    )

    resp = client.delete(f"/api/v1/admin/shop/product-types/{slug}", headers=HEADERS)
    assert resp.status_code == 200
    assert client.get(f"/api/v1/shop/product-types/{slug}").status_code == 404
