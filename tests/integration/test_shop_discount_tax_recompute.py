"""S96.6 — shop coupon discount honours the locked D-DiscountTax rule.

A coupon quotes a GROSS discount that reduces the NETTO; the tax recomputes on
the discounted netto (mirrors the booking plugin's S96.1). The discount is a
negative-amount CUSTOM line item (D-DiscountLineShape) carrying a NEGATIVE
``net_amount`` / ``tax_amount`` / per-rate ``tax_breakdown``. Because shop has
MULTIPLE product lines each with its own breakdown, the discount tax is split
proportionally over the AGGREGATED pre-discount per-rate tax across all lines.

Invariants across ALL lines (products + the negative discount line):
  - ``Σ line.net_amount == invoice.subtotal``
  - ``Σ line.tax_amount == invoice.tax_amount``
  - aggregated per-rate ``tax_breakdown`` (by code+rate) == ``invoice.tax_amount``
  - ``invoice.subtotal + invoice.tax_amount == invoice.total_amount``
"""
from collections import defaultdict
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


@pytest.fixture
def discount_ready(db):
    # The discount plugin is an optional, opt-in collaborator of shop checkout.
    # Skip (not error) when it is absent in isolated plugin CI.
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


def _make_product(db, *, stored_price, tax_rate=None, qty=100):
    from plugins.shop.shop.models.product import Product
    from plugins.shop.shop.models.warehouse import Warehouse
    from plugins.shop.shop.models.warehouse_stock import WarehouseStock

    product = Product(
        id=uuid4(),
        name="Widget",
        slug=f"widget-{uuid4().hex[:8]}",
        price=float(stored_price),
        is_active=True,
    )
    warehouse = Warehouse(
        id=uuid4(), name="Main", slug=f"main-{uuid4().hex[:8]}", is_default=True
    )
    db.session.add_all([product, warehouse])
    db.session.flush()
    if tax_rate is not None:
        tax = Tax(
            name=f"VAT{tax_rate}",
            code=f"VAT{int(tax_rate)}_{uuid4().hex[:6]}",
            rate=Decimal(str(tax_rate)),
        )
        db.session.add(tax)
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


def _make_fixed_coupon(db, *, code, value, scope, min_order=None):
    from plugins.discount.discount.models.coupon import Coupon
    from plugins.discount.discount.models.discount import (
        DiscountRule,
        DiscountType,
    )
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
            discount_type=DiscountType.FIXED_AMOUNT,
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


def _invoice_and_lines(db, invoice_id):
    from vbwd.models.invoice import UserInvoice
    from vbwd.models.invoice_line_item import InvoiceLineItem

    invoice = db.session.query(UserInvoice).filter_by(id=invoice_id).first()
    lines = db.session.query(InvoiceLineItem).filter_by(invoice_id=invoice_id).all()
    return invoice, lines


def _assert_invariants(invoice, lines):
    net_sum = sum((Decimal(str(line.net_amount)) for line in lines), Decimal("0.00"))
    tax_sum = sum((Decimal(str(line.tax_amount)) for line in lines), Decimal("0.00"))
    assert net_sum == Decimal(str(invoice.subtotal))
    assert tax_sum == Decimal(str(invoice.tax_amount))
    assert Decimal(str(invoice.subtotal)) + Decimal(str(invoice.tax_amount)) == Decimal(
        str(invoice.total_amount)
    )

    aggregated = defaultdict(lambda: Decimal("0.00"))
    for line in lines:
        for entry in line.tax_breakdown or []:
            key = (entry["code"], str(entry["rate"]))
            aggregated[key] += Decimal(str(entry["amount"]))
    assert sum(aggregated.values(), Decimal("0.00")) == Decimal(str(invoice.tax_amount))


def test_single_19pct_line_with_coupon_recomputes_tax(
    db, client, discount_ready, monkeypatch
):
    """19% product (net 100) + 11.90 gross coupon → tax drops to 17.10."""
    from plugins.discount.discount.models.discount import DiscountScope

    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product = _make_product(db, stored_price="100.00", tax_rate=19)
    _make_fixed_coupon(db, code="SAVE11", value="11.90", scope=DiscountScope.ECOMMERCE)
    _auth(monkeypatch, user)

    resp = client.post(
        "/api/v1/shop/cart/checkout",
        json={
            "items": [{"product_id": str(product.id), "quantity": 1}],
            "coupon_code": "SAVE11",
        },
        headers={"Authorization": "Bearer valid"},
    )
    assert resp.status_code == 201, resp.get_json()
    invoice, lines = _invoice_and_lines(db, resp.get_json()["invoice_id"])

    # Pre-discount: net 100.00, tax 19.00, gross 119.00.
    # 11.90 gross coupon → net_discount 10.00, tax_discount 1.90.
    assert invoice.subtotal == Decimal("90.00")
    assert invoice.tax_amount == Decimal("17.10")
    assert invoice.total_amount == Decimal("107.10")

    discount_line = next(
        line for line in lines if (line.extra_data or {}).get("discount")
    )
    assert discount_line.net_amount == Decimal("-10.00")
    assert discount_line.tax_amount == Decimal("-1.90")
    assert len(discount_line.tax_breakdown) == 1
    assert Decimal(str(discount_line.tax_breakdown[0]["amount"])) == Decimal("-1.90")
    _assert_invariants(invoice, lines)
    update_core_settings({"prices_mode_in_db": "NETTO"})


def test_heterogeneous_rates_split_discount_tax_proportionally(
    db, client, discount_ready, monkeypatch
):
    """A 19% line (net 100) + a 7% line (net 100) + coupon split across rates."""
    from plugins.discount.discount.models.discount import DiscountScope

    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product_19 = _make_product(db, stored_price="100.00", tax_rate=19)
    product_7 = _make_product(db, stored_price="100.00", tax_rate=7)
    # Pre-discount: net 200, tax 26 (19 + 7), gross 226.
    _make_fixed_coupon(db, code="SAVE22", value="22.60", scope=DiscountScope.ECOMMERCE)
    _auth(monkeypatch, user)

    resp = client.post(
        "/api/v1/shop/cart/checkout",
        json={
            "items": [
                {"product_id": str(product_19.id), "quantity": 1},
                {"product_id": str(product_7.id), "quantity": 1},
            ],
            "coupon_code": "SAVE22",
        },
        headers={"Authorization": "Bearer valid"},
    )
    assert resp.status_code == 201, resp.get_json()
    invoice, lines = _invoice_and_lines(db, resp.get_json()["invoice_id"])

    # 22.60 gross coupon on net 200 / total 226:
    #   net_discount = 22.60 * 200 / 226 = 20.00, tax_discount = 2.60.
    #   tax_discount split proportional to pre-discount tax (19 vs 7 of 26):
    #     19% share = 2.60 * 19/26 = 1.90, 7% share = 2.60 * 7/26 = 0.70.
    assert invoice.subtotal == Decimal("180.00")
    assert invoice.tax_amount == Decimal("23.40")
    assert invoice.total_amount == Decimal("203.40")

    discount_line = next(
        line for line in lines if (line.extra_data or {}).get("discount")
    )
    assert discount_line.net_amount == Decimal("-20.00")
    assert discount_line.tax_amount == Decimal("-2.60")
    by_rate = {
        str(entry["rate"]): Decimal(str(entry["amount"]))
        for entry in discount_line.tax_breakdown
    }
    assert by_rate["19.0"] == Decimal("-1.90") or by_rate["19"] == Decimal("-1.90")
    assert by_rate["7.0"] == Decimal("-0.70") or by_rate["7"] == Decimal("-0.70")
    _assert_invariants(invoice, lines)
    update_core_settings({"prices_mode_in_db": "NETTO"})


def test_untaxed_order_with_coupon_keeps_zero_tax(
    db, client, discount_ready, monkeypatch
):
    """Untaxed product + coupon → tax stays 0, net == gross, totals consistent."""
    from plugins.discount.discount.models.discount import DiscountScope

    update_core_settings({"prices_mode_in_db": "NETTO"})
    user = _make_user(db)
    product = _make_product(db, stored_price="30.00", tax_rate=None)
    _make_fixed_coupon(db, code="FLAT5", value="5.00", scope=DiscountScope.ECOMMERCE)
    _auth(monkeypatch, user)

    resp = client.post(
        "/api/v1/shop/cart/checkout",
        json={
            "items": [{"product_id": str(product.id), "quantity": 1}],
            "coupon_code": "FLAT5",
        },
        headers={"Authorization": "Bearer valid"},
    )
    assert resp.status_code == 201, resp.get_json()
    invoice, lines = _invoice_and_lines(db, resp.get_json()["invoice_id"])

    assert invoice.subtotal == Decimal("25.00")
    assert invoice.tax_amount == Decimal("0.00")
    assert invoice.total_amount == Decimal("25.00")

    discount_line = next(
        line for line in lines if (line.extra_data or {}).get("discount")
    )
    assert discount_line.net_amount == Decimal("-5.00")
    assert discount_line.tax_amount == Decimal("0.00")
    assert discount_line.tax_breakdown == []
    _assert_invariants(invoice, lines)
