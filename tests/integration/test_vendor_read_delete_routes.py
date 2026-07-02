"""Vendor self-service READ + DELETE routes (marketplace vendor-mode).

Mirrors ``test_vendor_mode_routes.py``: gated behind ``marketplace_enabled`` AND
the ``marketplace.vendor`` permission. A vendor lists / reads / deletes ONLY the
products they own (``vendor_id`` == their user id); categories carry no per-row
ownership so a vendor sees / edits / deletes every shop category.
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


def _create_product(client, token, name="Vendor Product"):
    resp = client.post(
        VENDOR_PRODUCTS_PATH, json=_product_body(name), headers=_auth(token)
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["product"]["id"]


def _create_category(client, token, name="Vendor Cat"):
    resp = client.post(
        VENDOR_CATEGORIES_PATH,
        json={"name": name, "slug": f"vc-{uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["category"]["id"]


# ── GET /vendor/products (list) ──────────────────────────────────────


def test_list_products_blocked_when_disabled(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-ld-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, False)

    resp = client.get(VENDOR_PRODUCTS_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_list_products_requires_permission(app, db, client, monkeypatch):
    _user, token = _register(app, f"plain-lp-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(VENDOR_PRODUCTS_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_list_products_returns_only_own(app, db, client, monkeypatch):
    owner, owner_token = _make_vendor(app, db, f"v-la-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"v-lb-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    mine = _create_product(client, owner_token, "Mine")
    theirs = _create_product(client, other_token, "Theirs")

    resp = client.get(VENDOR_PRODUCTS_PATH, headers=_auth(owner_token))
    assert resp.status_code == 200, resp.get_json()
    products = resp.get_json()["products"]
    ids = {product["id"] for product in products}
    assert mine in ids
    assert theirs not in ids
    assert all(p["vendor_id"] == str(owner.id) for p in products)


# ── GET /vendor/products/<id> (detail) ───────────────────────────────


def test_get_product_detail_own(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-gd-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.get(f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["id"] == product_id


def test_get_product_detail_missing_404(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-g4-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(f"{VENDOR_PRODUCTS_PATH}/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404, resp.get_json()


def test_get_product_detail_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"v-go-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"v-gx-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(other_token)
    )
    assert resp.status_code == 403, resp.get_json()


# ── DELETE /vendor/products/<id> ─────────────────────────────────────


def test_delete_own_product(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-do-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.delete(f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["success"] is True

    gone = client.get(f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(token))
    assert gone.status_code == 404, gone.get_json()


def test_delete_product_missing_404(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-d4-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.delete(f"{VENDOR_PRODUCTS_PATH}/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404, resp.get_json()


def test_delete_other_vendor_product_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"v-dx-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"v-dy-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.delete(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(other_token)
    )
    assert resp.status_code == 403, resp.get_json()

    # The row must survive a rejected delete.
    still = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}", headers=_auth(owner_token)
    )
    assert still.status_code == 200, still.get_json()


# ── GET /vendor/categories (list + detail) ───────────────────────────


def test_list_categories_blocked_when_disabled(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cld-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, False)

    resp = client.get(VENDOR_CATEGORIES_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_list_categories_returns_all(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"v-cla-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"v-clb-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    a = _create_category(client, owner_token, "Cat A")
    b = _create_category(client, other_token, "Cat B")

    resp = client.get(VENDOR_CATEGORIES_PATH, headers=_auth(owner_token))
    assert resp.status_code == 200, resp.get_json()
    ids = {category["id"] for category in resp.get_json()["categories"]}
    assert a in ids
    assert b in ids  # no per-row ownership — every category is visible


def test_get_category_detail(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cg-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    category_id = _create_category(client, token)
    resp = client.get(f"{VENDOR_CATEGORIES_PATH}/{category_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["category"]["id"] == category_id


def test_get_category_detail_missing_404(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cg4-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(f"{VENDOR_CATEGORIES_PATH}/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404, resp.get_json()


# ── PUT /vendor/categories/<id> ──────────────────────────────────────


def test_update_category(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cu-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    category_id = _create_category(client, token)
    resp = client.put(
        f"{VENDOR_CATEGORIES_PATH}/{category_id}",
        json={"name": "Renamed Cat", "description": "Updated"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["category"]
    assert body["name"] == "Renamed Cat"
    assert body["description"] == "Updated"


def test_update_category_missing_404(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cu4-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.put(
        f"{VENDOR_CATEGORIES_PATH}/{uuid4()}",
        json={"name": "Nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 404, resp.get_json()


# ── DELETE /vendor/categories/<id> ───────────────────────────────────


def test_delete_category(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cd-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    category_id = _create_category(client, token)
    resp = client.delete(
        f"{VENDOR_CATEGORIES_PATH}/{category_id}", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["success"] is True

    gone = client.get(f"{VENDOR_CATEGORIES_PATH}/{category_id}", headers=_auth(token))
    assert gone.status_code == 404, gone.get_json()


def test_delete_category_missing_404(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"v-cd4-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.delete(f"{VENDOR_CATEGORIES_PATH}/{uuid4()}", headers=_auth(token))
    assert resp.status_code == 404, resp.get_json()
