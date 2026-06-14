"""S72.4 — per-product netto/brutto price-display override (unit, no DB).

RED→GREEN contract (mirrors the subscription sibling):
- ``Product`` accepts ``price_display_mode`` (``None`` = inherit global,
  ``"netto"``/``"brutto"`` = override) and exposes it in ``to_dict()``.
- An invalid ``price_display_mode`` is rejected (``validate_price_display_mode``
  raises ``ValueError``; the admin route turns that into 400).
- ``ProductPricingService.get_product_pricing_payload`` exposes
  ``effective_display_mode = override ?? global`` and the global
  ``prices_display_mode`` value itself (so the fe-user consumer can render the
  "netto price" tag, which fires when effective==netto AND global==brutto).

S85.2: the money math now comes from the core ``PriceFactory`` (D1); the
display-mode pair is orthogonal and still resolved by the service.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.pricing.price_factory import PriceFactory
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product import validate_price_display_mode
import vbwd.pricing.display_mode as display_mode_module
from plugins.shop.shop.services.product_pricing_service import ProductPricingService


def _patch_global_mode(monkeypatch, mode: str) -> None:
    # S85.4: the display-mode pair is resolved by the single core helper
    # ``display_mode_fields`` (DRY) — patch its settings reader.
    monkeypatch.setattr(
        display_mode_module,
        "get_core_settings",
        lambda: {"prices_display_mode": mode},
    )


def _service(prices_mode_in_db: str = "NETTO") -> ProductPricingService:
    settings_reader = MagicMock(return_value={"prices_mode_in_db": prices_mode_in_db})
    currency_service = MagicMock()
    currency_service.get_default_currency.return_value = MagicMock(code="EUR")
    factory = PriceFactory(
        settings_reader=settings_reader, currency_service=currency_service
    )
    return ProductPricingService(price_factory=factory)


def _product(price_display_mode=None) -> Product:
    product = Product(
        name="Widget",
        slug="widget",
        price=100.0,
        price_display_mode=price_display_mode,
    )
    product.id = uuid4()
    product.taxes = []
    return product


def test_validate_accepts_none_netto_brutto():
    assert validate_price_display_mode(None) is None
    assert validate_price_display_mode("netto") == "netto"
    assert validate_price_display_mode("brutto") == "brutto"


def test_validate_rejects_unknown_value():
    with pytest.raises(ValueError):
        validate_price_display_mode("gross")


def test_to_dict_exposes_price_display_mode_default_none():
    product = _product(price_display_mode=None)

    data = product.to_dict()

    assert "price_display_mode" in data
    assert data["price_display_mode"] is None


def test_to_dict_exposes_price_display_mode_override():
    product = _product(price_display_mode="netto")

    data = product.to_dict()

    assert data["price_display_mode"] == "netto"


def test_pricing_exposes_global_mode_and_effective_inherits_when_override_none(
    monkeypatch,
):
    """Override is None → effective == global; global value also surfaced."""
    _patch_global_mode(monkeypatch, "brutto")
    product = _product(price_display_mode=None)

    result = _service().get_product_pricing_payload(product)

    assert result["prices_display_mode"] == "brutto"
    assert result["effective_display_mode"] == "brutto"


def test_pricing_override_wins_over_global(monkeypatch):
    """Override 'netto' under a 'brutto' global → effective == 'netto'."""
    _patch_global_mode(monkeypatch, "brutto")
    product = _product(price_display_mode="netto")

    result = _service().get_product_pricing_payload(product)

    assert result["prices_display_mode"] == "brutto"
    assert result["effective_display_mode"] == "netto"


def test_pricing_effective_follows_global_netto_when_no_override(monkeypatch):
    _patch_global_mode(monkeypatch, "netto")
    product = _product(price_display_mode=None)

    result = _service().get_product_pricing_payload(product)

    assert result["prices_display_mode"] == "netto"
    assert result["effective_display_mode"] == "netto"


def test_pricing_payload_stringifies_money_and_keeps_display_mode(monkeypatch):
    """The API payload helper stringifies money + carries the display-mode pair.

    This is the single source the list AND detail routes share, so both surface
    the identical ``pricing`` block.
    """
    _patch_global_mode(monkeypatch, "brutto")
    product = _product(price_display_mode="netto")

    payload = _service().get_product_pricing_payload(product)

    assert payload["net_amount"] == "100.00"
    assert payload["tax_amount"] == "0.00"
    assert payload["gross_amount"] == "100.00"
    assert payload["tax_rate"] == "0.00"
    assert payload["taxes"] == []
    assert payload["prices_display_mode"] == "brutto"
    assert payload["effective_display_mode"] == "netto"


def test_pricing_display_mode_present_even_with_assigned_taxes(monkeypatch):
    """The assigned-tax breakdown path must still carry the display-mode keys."""
    from vbwd.models.tax import Tax

    _patch_global_mode(monkeypatch, "brutto")
    tax = Tax(name="German VAT", code="VAT_DE", rate=Decimal("19.00"))
    tax.id = uuid4()
    product = _product(price_display_mode="netto")
    product.taxes = [tax]

    result = _service().get_product_pricing_payload(product)

    assert result["gross_amount"] == "119.00"
    assert result["prices_display_mode"] == "brutto"
    assert result["effective_display_mode"] == "netto"
