"""Checkout stamps the vendor id on the buyer invoice line (the money path).

When ``marketplace_enabled`` is True and a purchased product is vendor-owned,
the created invoice line's ``extra_data`` carries ``vendor_id`` = the vendor's
user id (the documented convention ``marketplace`` credits from). When the flag
is False, no stamp is written (classic behaviour unchanged).
"""
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User

from plugins.shop.shop import routes as shop_routes


@pytest.fixture
def client(app):
    return app.test_client()


def _make_user(db, *, prefix="buyer"):
    user = User(
        id=uuid4(),
        email=f"{prefix}-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.USER,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _vendor_product_with_stock(db, *, vendor_id, qty=10):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    product = Product(
        id=uuid4(),
        name="Vendor Widget",
        slug=f"vend-{uuid4().hex[:8]}",
        price=10.0,
        is_active=True,
        vendor_id=vendor_id,
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


def _vendor_line(db, invoice_id):
    from vbwd.models.invoice_line_item import InvoiceLineItem

    return db.session.query(InvoiceLineItem).filter_by(invoice_id=invoice_id).first()


def test_checkout_stamps_vendor_id_when_enabled(db, client, monkeypatch):
    vendor_id = _make_user(db, prefix="vendor").id
    buyer = _make_user(db)
    product = _vendor_product_with_stock(db, vendor_id=vendor_id)
    _auth(monkeypatch, buyer)
    monkeypatch.setattr(shop_routes, "marketplace_enabled", lambda: True)

    resp = _checkout(client, product)
    assert resp.status_code == 201, resp.get_json()

    line = _vendor_line(db, resp.get_json()["invoice_id"])
    assert line.extra_data.get("vendor_id") == str(vendor_id)


def test_checkout_does_not_stamp_when_disabled(db, client, monkeypatch):
    vendor_id = _make_user(db, prefix="vendor").id
    buyer = _make_user(db)
    product = _vendor_product_with_stock(db, vendor_id=vendor_id)
    _auth(monkeypatch, buyer)
    monkeypatch.setattr(shop_routes, "marketplace_enabled", lambda: False)

    resp = _checkout(client, product)
    assert resp.status_code == 201, resp.get_json()

    line = _vendor_line(db, resp.get_json()["invoice_id"])
    assert "vendor_id" not in line.extra_data


def test_checkout_platform_product_never_stamped(db, client, monkeypatch):
    buyer = _make_user(db)
    product = _vendor_product_with_stock(db, vendor_id=None)
    _auth(monkeypatch, buyer)
    monkeypatch.setattr(shop_routes, "marketplace_enabled", lambda: True)

    resp = _checkout(client, product)
    assert resp.status_code == 201, resp.get_json()

    line = _vendor_line(db, resp.get_json()["invoice_id"])
    assert "vendor_id" not in line.extra_data
