"""Digital products skip the checkout stock/inventory availability check.

A digital good has no inventory, so ``cart_checkout`` must NOT call
``block_stock`` for it — a digital product with zero available stock checks out
successfully. Physical products keep the existing check: insufficient stock
still fails with a 400 (``InsufficientStockError``).
"""
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


@pytest.fixture
def client(app):
    return app.test_client()


def _make_user(db):
    user = User(
        id=uuid4(),
        email=f"shop-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.USER,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _product_no_stock(db, *, is_digital):
    """Create an active product with NO warehouse stock (zero available)."""
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="No-Stock Widget",
        slug=f"nostock-{uuid4().hex[:8]}",
        price=10.0,
        is_active=True,
        is_digital=is_digital,
    )
    db.session.add(product)
    db.session.commit()
    return product


def _auth(monkeypatch, user):
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = user
    svc = MagicMock()
    svc.verify_token.return_value = str(user.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)


def _checkout(client, product):
    return client.post(
        "/api/v1/shop/cart/checkout",
        json={"items": [{"product_id": str(product.id), "quantity": 1}]},
        headers={"Authorization": "Bearer valid"},
    )


def test_digital_product_with_zero_stock_checks_out(db, client, monkeypatch):
    user = _make_user(db)
    product = _product_no_stock(db, is_digital=True)
    _auth(monkeypatch, user)

    resp = _checkout(client, product)

    assert resp.status_code == 201, resp.get_json()


def test_physical_product_with_zero_stock_still_fails(db, client, monkeypatch):
    user = _make_user(db)
    product = _product_no_stock(db, is_digital=False)
    _auth(monkeypatch, user)

    resp = _checkout(client, product)

    assert resp.status_code == 400, resp.get_json()
    assert "stock" in resp.get_json()["error"].lower()
