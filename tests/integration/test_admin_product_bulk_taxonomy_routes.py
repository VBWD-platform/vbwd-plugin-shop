"""Admin bulk category/tag assignment for shop products (integration).

The shop-admin product list needs to bulk-assign a category or tags to the
selected rows the same way the CMS pages admin does. These endpoints fan the
existing single-product assignment (the ``product.categories`` M2M and the core
``tags_and_custom_fields`` port) out over the selected ids in ONE committed
transaction.

Shop bulk convention: body ``{"product_ids": [...]}`` (never ``ids``); unknown
ids are skipped, not fatal; ``shop.products.manage`` is required. The response
is ``{"updated": <count>, "skipped": <count>}`` where ``updated`` is the number
of products found + written and ``skipped`` is the number of ids not found.

Semantics:
- ``assign-category`` ``mode=add`` (default): append the category if absent
  (idempotent); ``mode=replace``: set the product's categories to just this one.
- ``unassign-category``: remove the category from the selected products.
- ``assign-tags`` ``mode=add`` (default): union with each product's existing
  ``shop_product`` tags; ``mode=replace``: set the tags to exactly ``tag_slugs``.
- The category id resolves by UUID first, then by slug.
- A non-existent category is a 400 (whole request rejected before any write).
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


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


def _auth_as_admin(monkeypatch, admin, *, has_permission=True):
    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    monkeypatch.setattr(
        type(admin), "has_permission", lambda self, perm: has_permission
    )


def _make_product(db, *, name="Widget", slug=None):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name=name,
        slug=slug or f"widget-{uuid4().hex[:8]}",
        price=Decimal("9.99"),
        is_active=True,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _make_category(db, *, name="Tools", slug=None):
    from plugins.shop.shop.models.product_category import ProductCategory

    category = ProductCategory(
        id=uuid4(),
        name=name,
        slug=slug or f"tools-{uuid4().hex[:8]}",
    )
    db.session.add(category)
    db.session.commit()
    return category


def _category_slugs(db, product_id):
    from plugins.shop.shop.models.product import Product

    product = db.session.get(Product, product_id)
    db.session.refresh(product)
    return {category.slug for category in product.categories}


# ── assign-category ──────────────────────────────────────────────────


def test_assign_category_add_to_all_selected(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    first = _make_product(db)
    second = _make_product(db)
    category = _make_category(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={
            "product_ids": [str(first.id), str(second.id)],
            "category_id": str(category.id),
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"updated": 2, "skipped": 0}
    assert category.slug in _category_slugs(db, first.id)
    assert category.slug in _category_slugs(db, second.id)


def test_assign_category_resolves_by_slug(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    _make_category(db, slug="power-tools")

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={"product_ids": [str(product.id)], "category_id": "power-tools"},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["updated"] == 1
    assert "power-tools" in _category_slugs(db, product.id)


def test_assign_category_add_keeps_existing_categories(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    existing = _make_category(db, slug="existing")
    existing.products.append(product)
    db.session.commit()
    new_category = _make_category(db, slug="new-one")

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={"product_ids": [str(product.id)], "category_id": str(new_category.id)},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert _category_slugs(db, product.id) == {"existing", "new-one"}


def test_assign_category_replace_mode_sets_only_this_category(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    existing = _make_category(db, slug="existing")
    existing.products.append(product)
    db.session.commit()
    new_category = _make_category(db, slug="only-this")

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={
            "product_ids": [str(product.id)],
            "category_id": str(new_category.id),
            "mode": "replace",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert _category_slugs(db, product.id) == {"only-this"}


def test_assign_category_skips_unknown_product_ids(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    category = _make_category(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={
            "product_ids": [str(product.id), str(uuid4())],
            "category_id": str(category.id),
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"updated": 1, "skipped": 1}


def test_assign_category_unknown_category_is_400(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={"product_ids": [str(product.id)], "category_id": "does-not-exist"},
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_assign_category_requires_permission(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin, has_permission=False)
    product = _make_product(db)
    category = _make_category(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-category",
        json={"product_ids": [str(product.id)], "category_id": str(category.id)},
        headers=HEADERS,
    )

    assert resp.status_code == 403


# ── unassign-category ────────────────────────────────────────────────


def test_unassign_category_removes_from_selected(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    category = _make_category(db, slug="to-remove")
    category.products.append(product)
    db.session.commit()

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/unassign-category",
        json={"product_ids": [str(product.id)], "category_id": str(category.id)},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["updated"] == 1
    assert "to-remove" not in _category_slugs(db, product.id)


def test_unassign_category_unknown_category_is_400(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/unassign-category",
        json={"product_ids": [str(product.id)], "category_id": "nope"},
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


# ── assign-tags ──────────────────────────────────────────────────────


def _tags(app, product_id):
    with app.app_context():
        return set(
            app.container.tags_and_custom_fields().get_tags("shop_product", product_id)
        )


def test_assign_tags_add_unions_existing(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "shop_product", product.id, ["keep"]
        )

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-tags",
        json={"product_ids": [str(product.id)], "tag_slugs": ["new-a", "new-b"]},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["updated"] == 1
    assert _tags(app, product.id) == {"keep", "new-a", "new-b"}


def test_assign_tags_replace_sets_exactly(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "shop_product", product.id, ["old"]
        )

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-tags",
        json={
            "product_ids": [str(product.id)],
            "tag_slugs": ["fresh"],
            "mode": "replace",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert _tags(app, product.id) == {"fresh"}


def test_assign_tags_skips_unknown_product_ids(app, db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-tags",
        json={
            "product_ids": [str(product.id), str(uuid4())],
            "tag_slugs": ["x"],
        },
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json() == {"updated": 1, "skipped": 1}
    assert _tags(app, product.id) == {"x"}


def test_assign_tags_requires_permission(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin, has_permission=False)
    product = _make_product(db)

    resp = client.post(
        "/api/v1/admin/shop/products/bulk/assign-tags",
        json={"product_ids": [str(product.id)], "tag_slugs": ["x"]},
        headers=HEADERS,
    )

    assert resp.status_code == 403
