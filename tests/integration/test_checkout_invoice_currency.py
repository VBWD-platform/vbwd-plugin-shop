"""S99.0 — shop checkout creates the invoice in the CONFIGURED currency.

The invoice currency was hard-coded ``"EUR"``. The contract (S99) is one
billing currency = the ``default_currency`` core setting; the created invoice
must carry whatever is configured. Setting it to ``USD`` and asserting the
persisted ``invoice.currency == "USD"`` proves no literal remains. The setting
is restored to ``EUR`` at the end so the shared test state is unchanged.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.services.core_settings_store import update_core_settings


@pytest.fixture
def client(app):
    return app.test_client()


def _ensure_currency(db, code):
    from vbwd.models.currency import Currency
    from vbwd.repositories.currency_repository import CurrencyRepository

    repo = CurrencyRepository(db.session)
    if repo.find_by_code(code) is None:
        db.session.add(
            Currency(
                id=uuid4(),
                code=code,
                name=code,
                symbol="$" if code == "USD" else code,
                exchange_rate=Decimal("1.0"),
                decimal_places=2,
            )
        )
        db.session.commit()


def _make_user(db):
    user = User(
        id=uuid4(),
        email=f"shop-cur-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.USER,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _product_with_stock(db, *, qty=10):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    product = Product(
        id=uuid4(),
        name="Currency Widget",
        slug=f"cur-{uuid4().hex[:8]}",
        price=10.0,
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


def _auth(monkeypatch, user):
    from unittest.mock import MagicMock

    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = user
    svc = MagicMock()
    svc.verify_token.return_value = str(user.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)


def test_checkout_invoice_uses_configured_default_currency(db, client, monkeypatch):
    _ensure_currency(db, "EUR")
    _ensure_currency(db, "USD")
    update_core_settings({"active_currencies": ["EUR", "USD"]})
    update_core_settings({"default_currency": "USD"})
    try:
        user = _make_user(db)
        product = _product_with_stock(db)
        _auth(monkeypatch, user)

        resp = client.post(
            "/api/v1/shop/cart/checkout",
            json={"items": [{"product_id": str(product.id), "quantity": 1}]},
            headers={"Authorization": "Bearer valid"},
        )
        assert resp.status_code == 201, resp.get_json()

        from vbwd.models.invoice import UserInvoice

        invoice = db.session.get(UserInvoice, resp.get_json()["invoice_id"])
        assert invoice.currency == "USD"
    finally:
        update_core_settings({"default_currency": "EUR"})
        update_core_settings({"active_currencies": ["EUR"]})
