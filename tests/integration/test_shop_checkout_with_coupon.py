"""Integration: POST /api/v1/shop/cart/checkout applies a coupon discount.

Drives the shop checkout → checkout_price_adjustment_registry path with the
discount plugin's adjustment registered (ECOMMERCE scope):
  - a valid ECOMMERCE coupon adds a negative discount line + reduces the total,
    redeeming the coupon once
  - a coupon whose min-order is not met is rejected (4xx), no invoice committed
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def discount_ready(db):
    # The discount plugin is an optional, opt-in collaborator of shop checkout.
    # This cross-plugin coupon test only runs when discount is installed (the
    # full local suite); in isolated plugin CI it is absent, so skip not error.
    pytest.importorskip("plugins.discount.discount.models")
    import plugins.discount.discount.models  # noqa: F401

    db.create_all()
    from vbwd.services.checkout_price_adjustment_registry import (
        clear_price_adjustments,
        register_price_adjustment,
    )
    from plugins.discount.discount.checkout_adjustment import (
        checkout_price_adjustment,
    )

    register_price_adjustment("discount", checkout_price_adjustment)
    yield
    clear_price_adjustments()


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


def _make_product_with_stock(db, *, price, qty=100):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    product = Product(
        id=uuid4(),
        name="Widget",
        slug=f"widget-{uuid4().hex[:8]}",
        price=Decimal(price),
        is_active=True,
    )
    warehouse = Warehouse(
        id=uuid4(), name="Main", slug=f"main-{uuid4().hex[:8]}", is_default=True
    )
    db.session.add_all([product, warehouse])
    db.session.flush()
    db.session.add(
        WarehouseStock(
            id=uuid4(),
            warehouse_id=warehouse.id,
            product_id=product.id,
            quantity=qty,
            reserved=0,
        )
    )
    db.session.commit()
    return product


def _make_coupon(db, *, code, scope, dtype, value, min_order=None):
    from plugins.discount.discount.models.coupon import Coupon
    from plugins.discount.discount.models.discount import DiscountRule
    from plugins.discount.discount.repositories.coupon_repository import (
        CouponRepository,
    )
    from plugins.discount.discount.repositories.discount_repository import (
        DiscountRepository,
    )

    discount = DiscountRepository(db.session).save(
        DiscountRule(
            id=uuid4(),
            name=f"D {code}",
            slug=f"d-{code.lower()}",
            discount_type=dtype,
            value=Decimal(value),
            scope=scope,
            min_order_amount=Decimal(min_order) if min_order else None,
            is_active=True,
            priority=10,
        )
    )
    CouponRepository(db.session).save(
        Coupon(id=uuid4(), code=code, discount_id=discount.id, is_active=True)
    )


def _auth(monkeypatch, user):
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = user
    svc = MagicMock()
    svc.verify_token.return_value = str(user.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)


def test_shop_checkout_with_ecommerce_coupon_reduces_total(
    db, client, discount_ready, monkeypatch
):
    from plugins.discount.discount.models.discount import DiscountScope, DiscountType

    user = _make_user(db)
    product = _make_product_with_stock(db, price="30.00")
    _make_coupon(
        db,
        code="WELCOME5",
        scope=DiscountScope.ECOMMERCE,
        dtype=DiscountType.FIXED_AMOUNT,
        value="5.00",
        min_order="25.00",
    )
    _auth(monkeypatch, user)

    resp = client.post(
        "/api/v1/shop/cart/checkout",
        json={
            "items": [{"product_id": str(product.id), "quantity": 1}],
            "coupon_code": "WELCOME5",
        },
        headers={"Authorization": "Bearer valid"},
    )

    assert resp.status_code == 201, resp.get_json()
    assert Decimal(resp.get_json()["total"]) == Decimal("25.00")

    from plugins.discount.discount.repositories.coupon_repository import (
        CouponRepository,
    )

    assert CouponRepository(db.session).find_by_code("WELCOME5").current_uses == 1


def test_shop_checkout_rejects_coupon_below_min_order(
    db, client, discount_ready, monkeypatch
):
    from plugins.discount.discount.models.discount import DiscountScope, DiscountType

    user = _make_user(db)
    product = _make_product_with_stock(db, price="10.00")
    _make_coupon(
        db,
        code="WELCOME5",
        scope=DiscountScope.ECOMMERCE,
        dtype=DiscountType.FIXED_AMOUNT,
        value="5.00",
        min_order="25.00",
    )
    _auth(monkeypatch, user)

    resp = client.post(
        "/api/v1/shop/cart/checkout",
        json={
            "items": [{"product_id": str(product.id), "quantity": 1}],
            "coupon_code": "WELCOME5",
        },
        headers={"Authorization": "Bearer valid"},
    )

    assert resp.status_code == 400, resp.get_json()
    from vbwd.models.invoice import UserInvoice

    assert db.session.query(UserInvoice).filter_by(user_id=user.id).count() == 0
