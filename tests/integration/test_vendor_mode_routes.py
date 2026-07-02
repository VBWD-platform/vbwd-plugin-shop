"""Vendor self-service routes — gated, permission- and ownership-checked.

When ``marketplace_enabled`` is False the vendor surface is invisible (403);
when True a user holding ``marketplace.vendor`` can create products they own
and categories, but can never edit another vendor's product.
"""
from uuid import uuid4

import pytest

from plugins.shop.shop import routes as shop_routes


VENDOR_PRODUCTS_PATH = "/api/v1/shop/vendor/products"
VENDOR_CATEGORIES_PATH = "/api/v1/shop/vendor/categories"


@pytest.fixture
def client(app):
    return app.test_client()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _register(app, email):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    user_repository = UserRepository(db.session)
    auth_service = app.container.auth_service()
    if user_repository.find_by_email(email) is None:
        auth_service.register(email=email, password="Vendor123@")
        db.session.commit()
    user = user_repository.find_by_email(email)
    login = auth_service.login(email=email, password="Vendor123@")
    return user, login.token


def _grant_vendor_permission(db, user):
    """Attach a user access level carrying ``marketplace.vendor`` to ``user``."""
    from vbwd.models.role import Permission
    from vbwd.models.user_access_level import UserAccessLevel

    permission = (
        db.session.query(Permission).filter_by(name="marketplace.vendor").first()
    )
    if permission is None:
        permission = Permission(
            id=uuid4(),
            name="marketplace.vendor",
            description="Sell as a vendor",
            resource="marketplace",
            action="vendor",
        )
        db.session.add(permission)
    suffix = uuid4().hex[:8]
    level = UserAccessLevel(
        id=uuid4(),
        slug=f"vendor-{suffix}",
        name=f"Vendor {suffix}",
    )
    level.permissions.append(permission)
    user.assigned_user_access_levels.append(level)
    db.session.commit()


def _make_vendor(app, db, email):
    user, token = _register(app, email)
    _grant_vendor_permission(db, user)
    return user, token


def _enable_marketplace(monkeypatch, enabled):
    monkeypatch.setattr(shop_routes, "marketplace_enabled", lambda: enabled)


def _product_body(name="Vendor Product"):
    return {"name": name, "slug": f"vp-{uuid4().hex[:8]}", "price": 12.5}


def test_vendor_create_blocked_when_marketplace_disabled(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-off-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, False)

    resp = client.post(VENDOR_PRODUCTS_PATH, json=_product_body(), headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_vendor_create_requires_permission(app, db, client, monkeypatch):
    # A plain user (no marketplace.vendor) is rejected even when enabled.
    _user, token = _register(app, f"plain-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.post(VENDOR_PRODUCTS_PATH, json=_product_body(), headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_vendor_create_sets_vendor_id(app, db, client, monkeypatch):
    user, token = _make_vendor(app, db, f"v-create-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.post(
        VENDOR_PRODUCTS_PATH, json=_product_body("My Widget"), headers=_auth(token)
    )
    assert resp.status_code == 201, resp.get_json()
    product = resp.get_json()["product"]
    assert product["vendor_id"] == str(user.id)


def test_vendor_can_edit_own_product(app, db, client, monkeypatch):
    user, token = _make_vendor(app, db, f"v-own-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    create = client.post(
        VENDOR_PRODUCTS_PATH, json=_product_body(), headers=_auth(token)
    )
    product_id = create.get_json()["product"]["id"]

    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}",
        json={"name": "Renamed", "price": 20.0},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["name"] == "Renamed"
    assert resp.get_json()["product"]["vendor_id"] == str(user.id)


def test_vendor_cannot_edit_another_vendors_product(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"v-a-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"v-b-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    create = client.post(
        VENDOR_PRODUCTS_PATH, json=_product_body(), headers=_auth(owner_token)
    )
    product_id = create.get_json()["product"]["id"]

    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}",
        json={"name": "Hijacked"},
        headers=_auth(other_token),
    )
    assert resp.status_code == 403, resp.get_json()


def test_vendor_create_category(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cat-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.post(
        VENDOR_CATEGORIES_PATH,
        json={"name": "Vendor Cat", "slug": f"vc-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_json()


def test_vendor_category_blocked_when_disabled(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cat2-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, False)

    resp = client.post(
        VENDOR_CATEGORIES_PATH,
        json={"name": "Vendor Cat", "slug": f"vc-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert resp.status_code == 403, resp.get_json()
