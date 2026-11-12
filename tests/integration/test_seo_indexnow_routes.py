"""S154 D4 — the admin product/category routes trigger the IndexNow ping.

End-to-end through the real Flask route (not just the ``seo_indexnow`` unit),
so the wiring from ``routes.py`` into ``notify_product_changed`` /
``notify_category_changed`` is exercised. The cms import is monkeypatched at
``seo_indexnow._import_ping_indexnow_urls`` (no real cms/network needed), and
the fe-admin "indexable" switch is driven through the real ``config_store``.

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


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


class _IndexableConfigStore:
    """A fake ``config_store`` driving shop's fe-admin "indexable" switches."""

    def __init__(self, products_on, categories_on):
        self._config = {
            "seo_index_products": products_on,
            "seo_index_categories": categories_on,
        }

    def get_config(self, plugin_name):
        return self._config if plugin_name == "shop" else {}


HEADERS = {"Authorization": "Bearer valid"}


def _fake_ping(monkeypatch):
    from plugins.shop.shop.services import seo_indexnow

    ping = MagicMock()
    monkeypatch.setattr(seo_indexnow, "_import_ping_indexnow_urls", lambda: ping)
    return ping


def test_create_product_pings_indexnow_when_switch_on(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=True, categories_on=False),
    )

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={"name": "Blue Mug", "slug": "blue-mug", "price": "9.50"},
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    ping.assert_called_once_with(["/shop/product/blue-mug"])


def test_create_product_does_not_ping_when_switch_off(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=False, categories_on=False),
    )

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={"name": "Red Mug", "slug": "red-mug", "price": "9.50"},
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    ping.assert_not_called()


def test_update_product_pings_indexnow(app, db, client, monkeypatch):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.repositories.product_repository import ProductRepository

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = ProductRepository(db.session).save(
        Product(id=uuid4(), name="Widget", slug="widget-1", price=5.0, is_active=True)
    )
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=True, categories_on=False),
    )

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"price": "6.00"},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    ping.assert_called_once_with(["/shop/product/widget-1"])


def test_delete_product_pings_indexnow_with_its_slug(app, db, client, monkeypatch):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.repositories.product_repository import ProductRepository

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = ProductRepository(db.session).save(
        Product(id=uuid4(), name="Widget", slug="widget-2", price=5.0, is_active=True)
    )
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=True, categories_on=False),
    )

    resp = client.delete(
        f"/api/v1/admin/shop/products/{product.id}",
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    ping.assert_called_once_with(["/shop/product/widget-2"])


def test_create_category_pings_indexnow_when_switch_on(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=False, categories_on=True),
    )

    resp = client.post(
        "/api/v1/admin/shop/categories",
        json={"name": "Books", "slug": "books"},
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    ping.assert_called_once_with(["/shop/category/books"])


def test_bulk_delete_products_pings_once_for_every_deleted_slug(
    app, db, client, monkeypatch
):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.repositories.product_repository import ProductRepository

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    repo = ProductRepository(db.session)
    first = repo.save(
        Product(id=uuid4(), name="A", slug="bulk-a", price=1.0, is_active=True)
    )
    second = repo.save(
        Product(id=uuid4(), name="B", slug="bulk-b", price=1.0, is_active=True)
    )
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=True, categories_on=False),
    )

    resp = client.post(
        "/api/v1/admin/shop/products/bulk-delete",
        json={"product_ids": [str(first.id), str(second.id)]},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    ping.assert_called_once_with(["/shop/product/bulk-a", "/shop/product/bulk-b"])


def test_bulk_deactivate_products_pings_once(app, db, client, monkeypatch):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.repositories.product_repository import ProductRepository

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    repo = ProductRepository(db.session)
    product = repo.save(
        Product(id=uuid4(), name="C", slug="bulk-c", price=1.0, is_active=True)
    )
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=True, categories_on=False),
    )

    resp = client.post(
        "/api/v1/admin/shop/products/bulk-deactivate",
        json={"product_ids": [str(product.id)]},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    ping.assert_called_once_with(["/shop/product/bulk-c"])


def test_delete_category_does_not_ping_when_switch_off(app, db, client, monkeypatch):
    from plugins.shop.shop.models.product_category import ProductCategory
    from plugins.shop.shop.repositories.product_category_repository import (
        ProductCategoryRepository,
    )

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    category = ProductCategoryRepository(db.session).save(
        ProductCategory(id=uuid4(), name="Toys", slug="toys")
    )
    ping = _fake_ping(monkeypatch)
    monkeypatch.setattr(
        app,
        "config_store",
        _IndexableConfigStore(products_on=False, categories_on=False),
    )

    resp = client.delete(
        f"/api/v1/admin/shop/categories/{category.id}",
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    ping.assert_not_called()
