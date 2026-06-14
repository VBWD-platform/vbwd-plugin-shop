"""S85.2 — ``ProductPricingService`` computes via the core ``PriceFactory``.

Headline behaviour (mode-sensitivity): with the SAME stored ``price`` double and
a linked tax, flipping the global ``prices_mode_in_db`` between ``NETTO`` and
``BRUTTO`` yields a different net/gross. No bespoke tax math remains in the
service — all numbers come from the factory, and the payload embeds the
serialized ``Price`` object.
"""
from unittest.mock import MagicMock

from vbwd.pricing.price_factory import PriceFactory
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.services.product_pricing_service import ProductPricingService


class _FakeTax:
    def __init__(self, code, rate, name="VAT"):
        self.id = code
        self.code = code
        self.rate = rate
        self.name = name


def _factory(prices_mode_in_db):
    settings_reader = MagicMock(return_value={"prices_mode_in_db": prices_mode_in_db})
    currency_service = MagicMock()
    currency_service.get_default_currency.return_value = MagicMock(code="EUR")
    return PriceFactory(
        settings_reader=settings_reader, currency_service=currency_service
    )


def _product(price, taxes):
    product = Product(name="Widget", slug="widget", price=price)
    product.taxes = taxes
    return product


def test_netto_mode_adds_tax_on_top():
    service = ProductPricingService(price_factory=_factory("NETTO"))
    payload = service.get_product_pricing_payload(
        _product(100.0, [_FakeTax("VAT_DE", 19.0)])
    )
    assert payload["net_amount"] == "100.00"
    assert payload["gross_amount"] == "119.00"


def test_brutto_mode_extracts_net_from_gross():
    service = ProductPricingService(price_factory=_factory("BRUTTO"))
    payload = service.get_product_pricing_payload(
        _product(119.0, [_FakeTax("VAT_DE", 19.0)])
    )
    assert payload["gross_amount"] == "119.00"
    assert payload["net_amount"] == "100.00"


def test_mode_flip_changes_net_and_gross_for_same_stored_double():
    product = _product(100.0, [_FakeTax("VAT_DE", 19.0)])
    netto_mode = ProductPricingService(
        price_factory=_factory("NETTO")
    ).get_product_pricing_payload(product)
    brutto_mode = ProductPricingService(
        price_factory=_factory("BRUTTO")
    ).get_product_pricing_payload(product)
    assert netto_mode["gross_amount"] != brutto_mode["gross_amount"]
    assert netto_mode["net_amount"] != brutto_mode["net_amount"]


def test_payload_embeds_serialized_price_object():
    service = ProductPricingService(price_factory=_factory("NETTO"))
    payload = service.get_product_pricing_payload(
        _product(100.0, [_FakeTax("VAT_DE", 19.0)])
    )
    assert payload["price"]["netto"] == 100.0
    assert payload["price"]["brutto"] == 119.0
    assert payload["price"]["currency"] == "EUR"
    assert payload["price"]["taxes"][0]["code"] == "VAT_DE"


def test_taxless_product_net_equals_gross():
    service = ProductPricingService(price_factory=_factory("NETTO"))
    payload = service.get_product_pricing_payload(_product(50.0, []))
    assert payload["net_amount"] == payload["gross_amount"] == "50.00"
    assert payload["taxes"] == []


def test_service_calls_price_factory(monkeypatch):
    """Guard (DRY/D1): the service routes through PriceFactory, not inline math."""
    factory = _factory("NETTO")
    spy = MagicMock(wraps=factory.get_price_from_object)
    monkeypatch.setattr(factory, "get_price_from_object", spy)
    ProductPricingService(price_factory=factory).get_product_pricing_payload(
        _product(100.0, [_FakeTax("VAT_DE", 19.0)])
    )
    assert spy.called
