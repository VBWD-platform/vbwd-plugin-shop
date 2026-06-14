"""S72.4 — admin create/update product accept ``price_display_mode`` + the
public product payload exposes the display-mode pair (integration).

Contract:
- POST/PUT accept ``price_display_mode`` of ``null`` / ``"netto"`` / ``"brutto"``.
- An unknown value is rejected with 400.
- The persisted product's ``to_dict()`` reflects the stored override.
- The public ``GET /shop/products/<slug>`` ``pricing`` block exposes
  ``effective_display_mode`` (= override ?? global) AND the global
  ``prices_display_mode`` value (the fe-user consumer needs both).
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


def _make_product(db, price_display_mode=None):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="Widget",
        slug=f"widget-{uuid4().hex[:8]}",
        price=Decimal("100.00"),
        is_active=True,
        price_display_mode=price_display_mode,
    )
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


HEADERS = {"Authorization": "Bearer valid"}


def test_create_product_with_display_mode_override(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "NettoWidget",
            "price": "100.00",
            "price_display_mode": "netto",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["product"]["price_display_mode"] == "netto"


def test_create_product_default_display_mode_is_null(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "InheritWidget",
            "price": "100.00",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["product"]["price_display_mode"] is None


def test_create_product_rejects_unknown_display_mode(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "BadMode",
            "price": "100.00",
            "price_display_mode": "gross",
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_update_product_sets_display_mode_override(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"price_display_mode": "brutto"},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["price_display_mode"] == "brutto"


def test_update_product_clears_display_mode_to_inherit(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db, price_display_mode="netto")
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"price_display_mode": None},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["price_display_mode"] is None


def test_update_product_rejects_unknown_display_mode(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"price_display_mode": "weird"},
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_public_product_pricing_exposes_display_mode_pair_inherit(db, client):
    """Override None → effective == global; both surfaced on the public payload."""
    product = _make_product(db, price_display_mode=None)

    resp = client.get(f"/api/v1/shop/products/{product.slug}")

    assert resp.status_code == 200, resp.get_json()
    pricing = resp.get_json()["product"]["pricing"]
    # Global default is "brutto" (DEFAULT_CORE_SETTINGS); override None inherits.
    assert pricing["prices_display_mode"] == "brutto"
    assert pricing["effective_display_mode"] == "brutto"


def test_public_product_pricing_override_wins(db, client):
    """A netto override under the brutto global → effective == 'netto'."""
    product = _make_product(db, price_display_mode="netto")

    resp = client.get(f"/api/v1/shop/products/{product.slug}")

    assert resp.status_code == 200, resp.get_json()
    pricing = resp.get_json()["product"]["pricing"]
    assert pricing["prices_display_mode"] == "brutto"
    assert pricing["effective_display_mode"] == "netto"
