"""S85.2 — shop cart checkout charges ``Price.brutto`` and records the breakdown.

The charged amount (invoice grand total + line gross) comes from
``PriceFactory(...).brutto`` (D8). The line item persists the netto + per-tax
breakdown (in ``extra_data`` — invoice money columns stay ``Numeric(10,2)`` and
round at issue time, the one legitimate rounding boundary). Flipping the global
``prices_mode_in_db`` changes the recorded amount for the SAME stored double.
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


def test_netto_mode_charges_gross_total(db, client, monkeypatch):
    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product = _taxed_product_with_stock(db, Decimal("100.00"))
    _auth(monkeypatch, user)

    resp = _checkout(client, product)

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["total"] == "119.00"


def test_brutto_mode_charges_stored_double_as_gross(db, client, monkeypatch):
    update_core_settings({"prices_mode_in_db": "BRUTTO"})
    user = _make_user(db)
    product = _taxed_product_with_stock(db, Decimal("119.00"))
    _auth(monkeypatch, user)

    resp = _checkout(client, product)

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["total"] == "119.00"


def test_mode_flip_changes_charged_total_for_same_double(db, client, monkeypatch):
    user = _make_user(db)

    update_core_settings({"prices_mode_in_db": "NETTO"})
    netto_product = _taxed_product_with_stock(db, Decimal("100.00"))
    _auth(monkeypatch, user)
    netto_total = _checkout(client, netto_product).get_json()["total"]

    update_core_settings({"prices_mode_in_db": "BRUTTO"})
    brutto_product = _taxed_product_with_stock(db, Decimal("100.00"))
    brutto_total = _checkout(client, brutto_product).get_json()["total"]

    assert netto_total != brutto_total
    update_core_settings({"prices_mode_in_db": "NETTO"})


def test_line_item_records_net_and_tax_breakdown(db, client, monkeypatch):
    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product = _taxed_product_with_stock(db, Decimal("100.00"))
    _auth(monkeypatch, user)

    resp = _checkout(client, product)
    invoice_id = resp.get_json()["invoice_id"]

    from vbwd.models.invoice_line_item import InvoiceLineItem

    line = db.session.query(InvoiceLineItem).filter_by(invoice_id=invoice_id).first()
    breakdown = line.extra_data["price_breakdown"]
    net = Decimal(str(breakdown["netto"]))
    tax_sum = sum(Decimal(str(tax["amount"])) for tax in breakdown["taxes"])
    gross = Decimal(str(line.total_price))
    assert (net + tax_sum).quantize(Decimal("0.01")) == gross.quantize(Decimal("0.01"))
