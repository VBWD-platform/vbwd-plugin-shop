"""S85.4 — shop cart checkout persists first-class per-rate tax columns.

The invoice line item records ``net_amount`` / ``tax_amount`` / ``tax_breakdown``
(not just free-form metadata) and the invoice rolls ``subtotal`` / ``tax_amount``
/ ``total_amount`` up from the lines. The charged total stays ``Price.brutto``
(D8). Flipping the global ``prices_mode_in_db`` changes the recorded net/tax for
the same stored price.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.tax import Tax
from vbwd.models.user import User
from vbwd.services.core_settings_store import update_core_settings


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


def _taxed_product_with_stock(db, stored_price, *, qty=100):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    tax = Tax(name="VAT", code=f"VAT_{uuid4().hex[:6]}", rate=Decimal("19.00"))
    product = Product(
        id=uuid4(),
        name="Charged Widget",
        slug=f"charged-{uuid4().hex[:8]}",
        price=float(stored_price),
        is_active=True,
    )
    warehouse = Warehouse(
        id=uuid4(), name="Main", slug=f"main-{uuid4().hex[:8]}", is_default=True
    )
    db.session.add_all([tax, product, warehouse])
    db.session.flush()
    product.taxes = [tax]
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


def _line_and_invoice(db, invoice_id):
    from vbwd.models.invoice import UserInvoice
    from vbwd.models.invoice_line_item import InvoiceLineItem

    line = db.session.query(InvoiceLineItem).filter_by(invoice_id=invoice_id).first()
    invoice = db.session.query(UserInvoice).filter_by(id=invoice_id).first()
    return line, invoice


def test_netto_mode_records_line_columns_and_invoice_rollup(db, client, monkeypatch):
    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product = _taxed_product_with_stock(db, Decimal("100.00"))
    _auth(monkeypatch, user)

    resp = _checkout(client, product)
    assert resp.status_code == 201, resp.get_json()
    invoice_id = resp.get_json()["invoice_id"]

    line, invoice = _line_and_invoice(db, invoice_id)
    assert line.net_amount == Decimal("100.00")
    assert line.tax_amount == Decimal("19.00")
    assert line.total_price == Decimal("119.00")  # gross unchanged
    assert line.tax_breakdown[0]["code"] == product.taxes[0].code
    assert Decimal(str(line.tax_breakdown[0]["amount"])) == Decimal("19.00")

    assert invoice.subtotal == Decimal("100.00")
    assert invoice.tax_amount == Decimal("19.00")
    assert invoice.total_amount == Decimal("119.00")


def test_brutto_mode_changes_recorded_net_and_tax(db, client, monkeypatch):
    update_core_settings({"prices_mode_in_db": "BRUTTO"})
    user = _make_user(db)
    product = _taxed_product_with_stock(db, Decimal("119.00"))
    _auth(monkeypatch, user)

    resp = _checkout(client, product)
    assert resp.status_code == 201, resp.get_json()
    line, invoice = _line_and_invoice(db, resp.get_json()["invoice_id"])

    assert line.net_amount == Decimal("100.00")
    assert line.tax_amount == Decimal("19.00")
    assert line.total_price == Decimal("119.00")  # gross == charge
    update_core_settings({"prices_mode_in_db": "NETTO"})
