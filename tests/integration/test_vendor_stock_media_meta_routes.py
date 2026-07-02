"""Vendor self-service stock / images / tags / custom-field routes.

Mirrors ``test_vendor_read_delete_routes.py``: every route is gated behind
``marketplace_enabled`` AND the ``marketplace.vendor`` permission, and every
product-scoped route enforces ``vendor_id == g.user_id`` ownership (a foreign
vendor gets 403). The underlying primitives are the SAME the admin routes use
(``WarehouseStockRepository`` upsert, the CMS image chain, the core
``tags_and_custom_fields()`` port) — vendor + admin must never diverge.
"""
from uuid import uuid4

import pytest

from plugins.shop.shop import routes as shop_routes


VENDOR_PRODUCTS_PATH = "/api/v1/shop/vendor/products"
VENDOR_WAREHOUSES_PATH = "/api/v1/shop/vendor/warehouses"
VENDOR_FIELD_DEFS_PATH = "/api/v1/shop/vendor/product-custom-field-defs"
VENDOR_TAGS_CATALOG_PATH = "/api/v1/shop/vendor/product-tags-catalog"


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


def _create_active_warehouse(db, name="Vendor WH"):
    from plugins.shop.shop.models.warehouse import Warehouse

    warehouse = Warehouse(
        id=uuid4(),
        name=name,
        slug=f"wh-{uuid4().hex[:8]}",
        is_active=True,
    )
    db.session.add(warehouse)
    db.session.commit()
    return warehouse


def _create_field_def(db, key="material", field_type="text"):
    from vbwd.models.custom_field_def import CustomFieldDef

    definition = CustomFieldDef(
        id=uuid4(),
        entity_type="shop_product",
        key=key,
        label=key.title(),
        type=field_type,
        is_active=True,
    )
    db.session.add(definition)
    db.session.commit()
    return definition


# ── GET /vendor/warehouses ───────────────────────────────────────────


def test_warehouses_blocked_when_disabled(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vw-d-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, False)

    resp = client.get(VENDOR_WAREHOUSES_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_warehouses_requires_permission(app, db, client, monkeypatch):
    _user, token = _register(app, f"plain-w-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(VENDOR_WAREHOUSES_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_warehouses_lists_active_only(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vw-a-{uuid4().hex[:6]}@example.com")
    warehouse = _create_active_warehouse(db)
    _enable_marketplace(monkeypatch, True)

    resp = client.get(VENDOR_WAREHOUSES_PATH, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    warehouses = resp.get_json()["warehouses"]
    ids = {row["id"] for row in warehouses}
    assert str(warehouse.id) in ids
    assert all("name" in row and "id" in row for row in warehouses)


# ── GET / PUT /vendor/products/<id>/stock ────────────────────────────


def test_stock_get_own_product(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vs-g-{uuid4().hex[:6]}@example.com")
    warehouse = _create_active_warehouse(db)
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock",
        json={"warehouse_id": str(warehouse.id), "quantity": 7},
        headers=_auth(token),
    )

    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.get_json()
    rows = resp.get_json()["stock"]
    assert len(rows) == 1
    assert rows[0]["quantity"] == 7
    assert rows[0]["warehouse_name"] == warehouse.name


def test_stock_get_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vs-o-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vs-x-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock", headers=_auth(other_token)
    )
    assert resp.status_code == 403, resp.get_json()


def test_stock_put_upserts(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vs-p-{uuid4().hex[:6]}@example.com")
    warehouse = _create_active_warehouse(db)
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)

    created = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock",
        json={"warehouse_id": str(warehouse.id), "quantity": 5},
        headers=_auth(token),
    )
    assert created.status_code == 200, created.get_json()
    assert created.get_json()["stock"]["quantity"] == 5

    updated = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock",
        json={"warehouse_id": str(warehouse.id), "quantity": 11},
        headers=_auth(token),
    )
    assert updated.status_code == 200, updated.get_json()
    assert updated.get_json()["stock"]["quantity"] == 11


def test_stock_put_requires_warehouse_id(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vs-r-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock",
        json={"quantity": 3},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.get_json()


def test_stock_put_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vs-po-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vs-px-{uuid4().hex[:6]}@example.com")
    warehouse = _create_active_warehouse(db)
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock",
        json={"warehouse_id": str(warehouse.id), "quantity": 1},
        headers=_auth(other_token),
    )
    assert resp.status_code == 403, resp.get_json()


def test_stock_get_disabled_403(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vs-dd-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)
    product_id = _create_product(client, token)

    _enable_marketplace(monkeypatch, False)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/stock", headers=_auth(token)
    )
    assert resp.status_code == 403, resp.get_json()


# ── Images ───────────────────────────────────────────────────────────


def test_images_list_own_product(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vi-l-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/images", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["images"] == []


def test_images_list_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vi-o-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vi-x-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/images", headers=_auth(other_token)
    )
    assert resp.status_code == 403, resp.get_json()


def test_images_upload_owner_reaches_cms_guard(app, db, client, monkeypatch):
    """Owner upload reaches the CMS chain: 201 if CMS present, else the 501 guard.

    Never 403/404/500 for the owner — that would mean ownership or the CMS guard
    is broken. Kept light because the CMS plugin may be absent in the shop-only
    integration env.
    """
    _user, token = _make_vendor(app, db, f"vi-u-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.post(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/images",
        data={"file": (__import__("io").BytesIO(b"img-bytes"), "pic.jpg")},
        content_type="multipart/form-data",
        headers=_auth(token),
    )
    assert resp.status_code in (201, 501), resp.get_json()


def test_images_upload_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vi-uo-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vi-ux-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.post(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/images",
        data={"file": (__import__("io").BytesIO(b"img-bytes"), "pic.jpg")},
        content_type="multipart/form-data",
        headers=_auth(other_token),
    )
    assert resp.status_code == 403, resp.get_json()


# ── Tags ─────────────────────────────────────────────────────────────


def test_tags_get_empty_by_default(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vt-g-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.get(f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags", headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["tags"] == []


def test_tags_put_replaces(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vt-p-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags",
        json={"tags": ["featured", "new"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    assert set(resp.get_json()["tags"]) == {"featured", "new"}

    read = client.get(f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags", headers=_auth(token))
    assert set(read.get_json()["tags"]) == {"featured", "new"}


def test_tags_put_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vt-o-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vt-x-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags",
        json={"tags": ["hack"]},
        headers=_auth(other_token),
    )
    assert resp.status_code == 403, resp.get_json()


def test_tags_put_requires_list(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vt-r-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags",
        json={"tags": "not-a-list"},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.get_json()


# ── Custom fields ────────────────────────────────────────────────────


def test_custom_fields_get_empty_by_default(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vc-g-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.get(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/custom-fields", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["custom_fields"] == {}


def test_custom_fields_put_upserts(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vc-p-{uuid4().hex[:6]}@example.com")
    _create_field_def(db, key=f"material_{uuid4().hex[:6]}")
    _enable_marketplace(monkeypatch, True)

    # Re-read the def key created above.
    from vbwd.models.custom_field_def import CustomFieldDef

    field_key = (
        db.session.query(CustomFieldDef)
        .filter_by(entity_type="shop_product")
        .order_by(CustomFieldDef.created_at.desc())
        .first()
        .key
    )

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/custom-fields",
        json={"custom_fields": {field_key: "oak"}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["custom_fields"][field_key] == "oak"


def test_custom_fields_put_unknown_key_400(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vc-u-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/custom-fields",
        json={"custom_fields": {"nope_unknown_key": "x"}},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.get_json()


def test_custom_fields_put_other_vendor_403(app, db, client, monkeypatch):
    _owner, owner_token = _make_vendor(app, db, f"vc-o-{uuid4().hex[:6]}@example.com")
    _other, other_token = _make_vendor(app, db, f"vc-x-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, owner_token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/custom-fields",
        json={"custom_fields": {"any": "x"}},
        headers=_auth(other_token),
    )
    assert resp.status_code == 403, resp.get_json()


def test_custom_fields_put_requires_object(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vc-r-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    product_id = _create_product(client, token)
    resp = client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/custom-fields",
        json={"custom_fields": ["not", "an", "object"]},
        headers=_auth(token),
    )
    assert resp.status_code == 400, resp.get_json()


# ── Catalog metadata (no per-row ownership) ──────────────────────────


def test_field_defs_catalog(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vd-c-{uuid4().hex[:6]}@example.com")
    _create_field_def(db, key=f"colour_{uuid4().hex[:6]}", field_type="text")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(VENDOR_FIELD_DEFS_PATH, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    defs = resp.get_json()["custom_fields"]
    assert isinstance(defs, list)
    assert all("key" in d and "type" in d for d in defs)


def test_field_defs_catalog_requires_permission(app, db, client, monkeypatch):
    _user, token = _register(app, f"plain-d-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    resp = client.get(VENDOR_FIELD_DEFS_PATH, headers=_auth(token))
    assert resp.status_code == 403, resp.get_json()


def test_tags_catalog(app, db, client, monkeypatch):
    _user, token = _make_vendor(app, db, f"vtc-c-{uuid4().hex[:6]}@example.com")
    _enable_marketplace(monkeypatch, True)

    # Attaching a tag auto-creates it in the catalog (global scope).
    product_id = _create_product(client, token)
    client.put(
        f"{VENDOR_PRODUCTS_PATH}/{product_id}/tags",
        json={"tags": ["catalogtag"]},
        headers=_auth(token),
    )

    resp = client.get(VENDOR_TAGS_CATALOG_PATH, headers=_auth(token))
    assert resp.status_code == 200, resp.get_json()
    tags = resp.get_json()["tags"]
    assert isinstance(tags, list)
    slugs = {row["slug"] for row in tags}
    assert "catalogtag" in slugs
    assert all(
        "slug" in row and "name" in row and "parent_entity_type" in row for row in tags
    )
