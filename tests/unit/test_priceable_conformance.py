"""S85.1 — Product conforms to the core ``Priceable`` protocol.

After the storage migration the product exposes ``raw_price`` (a float reading
the stored ``price``) and keeps its ``taxes`` relationship; the dropped
``currency`` / ``price_float`` columns no longer exist; and ``to_dict()`` no
longer carries those keys.
"""
from uuid import uuid4

from vbwd.pricing.priceable import Priceable
from plugins.shop.shop.models.product import Product


def _product() -> Product:
    product = Product(name="Widget", slug="widget", price=19.99)
    product.id = uuid4()
    product.taxes = []
    return product


def test_product_raw_price_returns_stored_price_float():
    product = _product()
    assert product.raw_price == 19.99
    assert isinstance(product.raw_price, float)


def test_product_has_no_currency_or_price_float_column():
    assert not hasattr(Product, "currency")
    assert not hasattr(Product, "price_float")


def test_product_has_taxes_relationship():
    assert hasattr(Product, "taxes")
    assert list(_product().taxes) == []


def test_to_dict_drops_currency_and_price_float_keys():
    product_dict = _product().to_dict()
    assert "currency" not in product_dict
    assert "price_float" not in product_dict


def test_product_satisfies_priceable_protocol():
    assert isinstance(_product(), Priceable)
