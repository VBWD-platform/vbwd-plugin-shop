"""S72.3 — tax assignment on shop Product (unit, no DB).

RED→GREEN contract:
- ``Product.to_dict()`` exposes ``tax_ids: [<id>]`` and resolved
  ``taxes: [{id, code, name, rate}]`` from the M2M ``taxes`` relationship,
  while the legacy ``tax_class`` string is preserved.
- ``ProductPricingService.get_product_pricing_payload`` (S85.2: via the core
  ``PriceFactory``) sums the rates of the assigned taxes into net/tax/gross.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from vbwd.models.tax import Tax
from vbwd.pricing.price_factory import PriceFactory
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.services.product_pricing_service import ProductPricingService


def _service(prices_mode_in_db: str = "NETTO") -> ProductPricingService:
    settings_reader = MagicMock(return_value={"prices_mode_in_db": prices_mode_in_db})
    currency_service = MagicMock()
    currency_service.get_default_currency.return_value = MagicMock(code="EUR")
    factory = PriceFactory(
        settings_reader=settings_reader, currency_service=currency_service
    )
    return ProductPricingService(price_factory=factory)


def _fake_tax(code: str, name: str, rate: str) -> Tax:
    """A real core ``Tax`` instance (no DB) — exercises ``calculate``."""
    tax = Tax(name=name, code=code, rate=Decimal(rate))
    tax.id = uuid4()
    return tax


def _product(price: float = 100.0, taxes=None) -> Product:
    product = Product()
    product.id = uuid4()
    product.name = "Widget"
    product.slug = "widget"
    product.description = None
    product.sku = None
    product.price = price
    product.is_active = True
    product.has_variants = False
    product.weight = None
    product.dimensions = {}
    product.tax_class = "standard"
    product.images = []
    product.variants = []
    product.created_at = None
    product.updated_at = None
    # The relationship is normally lazy-loaded; in-memory we set it directly.
    product.taxes = taxes or []
    return product


def test_to_dict_exposes_tax_ids_and_resolved_taxes():
    vat = _fake_tax("VAT_DE", "German VAT", "19.00")
    reduced = _fake_tax("VAT_DE_RED", "German VAT (reduced)", "7.00")
    product = _product(taxes=[vat, reduced])

    data = product.to_dict()

    assert data["tax_ids"] == [str(vat.id), str(reduced.id)]
    assert data["taxes"] == [
        {"id": str(vat.id), "code": "VAT_DE", "name": "German VAT", "rate": "19.00"},
        {
            "id": str(reduced.id),
            "code": "VAT_DE_RED",
            "name": "German VAT (reduced)",
            "rate": "7.00",
        },
    ]
    # Legacy back-compat field stays.
    assert data["tax_class"] == "standard"


def test_to_dict_no_taxes_yields_empty_lists():
    product = _product(taxes=[])

    data = product.to_dict()

    assert data["tax_ids"] == []
    assert data["taxes"] == []
    assert data["tax_class"] == "standard"


def test_pricing_sums_assigned_tax_rates_into_net_tax_gross():
    """Assigned taxes (19% + 7% = 26%) take precedence; net=price, tax=26,
    gross=126 on a 100.00 product."""
    product = _product(
        price=100.0,
        taxes=[
            _fake_tax("VAT_DE", "German VAT", "19.00"),
            _fake_tax("VAT_DE_RED", "German VAT (reduced)", "7.00"),
        ],
    )

    result = _service().get_product_pricing_payload(product)

    assert result["net_amount"] == "100.00"
    assert result["tax_amount"] == "26.00"
    assert result["gross_amount"] == "126.00"
    assert result["tax_rate"] == "26.00"
    assert [tax["code"] for tax in result["taxes"]] == ["VAT_DE", "VAT_DE_RED"]


def test_pricing_falls_back_to_bare_net_when_no_taxes_assigned():
    """With no assigned taxes pricing reflects the bare net price (the legacy
    tax_class carries no rate in shop today)."""
    product = _product(price=100.0, taxes=[])

    result = _service().get_product_pricing_payload(product)

    assert result["net_amount"] == "100.00"
    assert result["tax_amount"] == "0.00"
    assert result["gross_amount"] == "100.00"
    assert result["tax_rate"] == "0.00"
    assert result["taxes"] == []
