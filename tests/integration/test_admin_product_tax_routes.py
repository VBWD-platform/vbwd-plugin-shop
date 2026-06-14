"""S72.3 — admin create/update product accept ``tax_ids`` (integration).

Contract:
- POST/PUT accept ``tax_ids: [uuid]``; each must exist AND be active.
- Update is a replace-set; an empty list clears the assignment; duplicate ids
  are deduped (order-preserving).
- A nonexistent or inactive tax id is rejected with 400.
- The legacy ``tax_class`` string is preserved alongside the M2M.
- The persisted product's ``to_dict()`` reflects the assigned taxes.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.tax import Tax


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


def _make_tax(db, *, is_active=True, rate="19.00"):
    tax = Tax(
        id=uuid4(),
        name=f"Tax {uuid4().hex[:6]}",
        code=f"TX_{uuid4().hex[:6]}",
        rate=Decimal(rate),
        is_active=is_active,
    )
    db.session.add(tax)
    db.session.commit()
    return tax


def _make_product(db):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="Widget",
        slug=f"widget-{uuid4().hex[:8]}",
        price=Decimal("100.00"),
        is_active=True,
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


def test_create_product_with_tax_ids_persists_m2m_deduped(db, client, monkeypatch):
    admin = _make_admin(db)
    tax_one = _make_tax(db)
    tax_two = _make_tax(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Taxed Widget",
            "price": "100.00",
            "tax_class": "reduced",
            "tax_ids": [str(tax_one.id), str(tax_two.id), str(tax_one.id)],
        },
        headers=HEADERS,
    )

    assert resp.status_code == 201, resp.get_json()
    product = resp.get_json()["product"]
    # Deduped, order-preserving.
    assert product["tax_ids"] == [str(tax_one.id), str(tax_two.id)]
    # Legacy field preserved.
    assert product["tax_class"] == "reduced"


def test_create_product_rejects_inactive_tax(db, client, monkeypatch):
    admin = _make_admin(db)
    inactive = _make_tax(db, is_active=False)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Bad Widget",
            "price": "10.00",
            "tax_ids": [str(inactive.id)],
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_create_product_rejects_unknown_tax(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.post(
        "/api/v1/admin/shop/products",
        json={
            "name": "Ghost Widget",
            "price": "10.00",
            "tax_ids": [str(uuid4())],
        },
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_update_product_replace_set_of_tax_ids(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    first = _make_tax(db)
    second = _make_tax(db)
    product.taxes = [first]
    db.session.commit()
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"tax_ids": [str(second.id)]},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["tax_ids"] == [str(second.id)]


def test_update_product_empty_tax_ids_clears_assignment(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    tax = _make_tax(db)
    product.taxes = [tax]
    db.session.commit()
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"tax_ids": []},
        headers=HEADERS,
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["product"]["tax_ids"] == []


def test_update_product_rejects_unknown_tax(db, client, monkeypatch):
    admin = _make_admin(db)
    product = _make_product(db)
    _auth_as_admin(monkeypatch, admin)

    resp = client.put(
        f"/api/v1/admin/shop/products/{product.id}",
        json={"tax_ids": [str(uuid4())]},
        headers=HEADERS,
    )

    assert resp.status_code == 400, resp.get_json()


def test_public_product_detail_pricing_sums_assigned_taxes(db, client):
    """The public product detail response reflects the summed applied taxes."""
    product = _make_product(db)
    vat = _make_tax(db, rate="19.00")
    reduced = _make_tax(db, rate="7.00")
    product.taxes = [vat, reduced]
    db.session.commit()

    resp = client.get(f"/api/v1/shop/products/{product.slug}")

    assert resp.status_code == 200, resp.get_json()
    pricing = resp.get_json()["product"]["pricing"]
    assert pricing["net_amount"] == "100.00"
    assert pricing["tax_amount"] == "26.00"
    assert pricing["gross_amount"] == "126.00"
    assert pricing["tax_rate"] == "26.00"
    assert {tax["code"] for tax in pricing["taxes"]} == {vat.code, reduced.code}
