"""S101.0 — ProductVariantService unit tests (MagicMock repo, no DB).

Contract:
- create appends at the next sort_order; name required; duplicate sku rejected.
- update mutates editable attributes; an unknown variant raises.
- delete / toggle / reorder operate only on the product's own variants.
- pricing flows through the injected ``PriceFactory`` (no new tax/round path).
"""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from plugins.shop.shop.models.product_variant import ProductVariant
from plugins.shop.shop.services.product_variant_service import (
    DuplicateVariantSkuError,
    ProductVariantService,
    VariantNotFoundError,
)


def _service(repo=None, price_factory=None):
    return ProductVariantService(
        repo or MagicMock(),
        price_factory or MagicMock(),
    )


def test_create_variant_appends_at_next_sort_order():
    repo = MagicMock()
    repo.find_by_sku.return_value = None
    repo.next_sort_order.return_value = 3
    repo.save.side_effect = lambda variant: variant
    product_id = uuid4()

    variant = _service(repo).create_variant(
        product_id, {"name": "Pack of 20", "sku": "PZN-12345", "price": 4.99}
    )

    assert variant.sort_order == 3
    assert variant.name == "Pack of 20"
    assert variant.sku == "PZN-12345"
    repo.save.assert_called_once()


def test_create_variant_requires_name():
    with pytest.raises(ValueError):
        _service().create_variant(uuid4(), {"sku": "X"})


def test_create_variant_rejects_duplicate_sku():
    repo = MagicMock()
    repo.find_by_sku.return_value = ProductVariant(id=uuid4(), name="other")
    with pytest.raises(DuplicateVariantSkuError):
        _service(repo).create_variant(uuid4(), {"name": "x", "sku": "DUP"})


def test_update_variant_mutates_editable_fields():
    product_id = uuid4()
    variant = ProductVariant(id=uuid4(), product_id=product_id, name="old")
    repo = MagicMock()
    repo.find_by_id.return_value = variant
    repo.save.side_effect = lambda v: v

    updated = _service(repo).update_variant(
        product_id, variant.id, {"name": "new", "is_active": False}
    )

    assert updated.name == "new"
    assert updated.is_active is False


def test_update_variant_unknown_raises():
    repo = MagicMock()
    repo.find_by_id.return_value = None
    with pytest.raises(VariantNotFoundError):
        _service(repo).update_variant(uuid4(), uuid4(), {"name": "x"})


def test_update_variant_belonging_to_other_product_raises():
    repo = MagicMock()
    repo.find_by_id.return_value = ProductVariant(
        id=uuid4(), product_id=uuid4(), name="x"
    )
    with pytest.raises(VariantNotFoundError):
        _service(repo).update_variant(uuid4(), uuid4(), {"name": "x"})


def test_toggle_variant_flips_is_active():
    product_id = uuid4()
    variant = ProductVariant(
        id=uuid4(), product_id=product_id, name="x", is_active=True
    )
    repo = MagicMock()
    repo.find_by_id.return_value = variant
    repo.save.side_effect = lambda v: v

    result = _service(repo).toggle_variant(product_id, variant.id)
    assert result.is_active is False


def test_reorder_variants_sets_sort_order_by_position():
    product_id = uuid4()
    first = ProductVariant(id=uuid4(), product_id=product_id, name="a", sort_order=0)
    second = ProductVariant(id=uuid4(), product_id=product_id, name="b", sort_order=1)
    repo = MagicMock()
    repo.list_for_product.return_value = [first, second]
    repo.save.side_effect = lambda v: v

    _service(repo).reorder_variants(product_id, [second.id, first.id])

    assert second.sort_order == 0
    assert first.sort_order == 1


def test_reorder_rejects_foreign_variant():
    product_id = uuid4()
    repo = MagicMock()
    repo.list_for_product.return_value = []
    with pytest.raises(VariantNotFoundError):
        _service(repo).reorder_variants(product_id, [uuid4()])


def test_get_variant_pricing_delegates_to_price_factory():
    price_factory = MagicMock()
    price = MagicMock()
    price.netto = 4.0
    price.brutto = 4.76
    price.taxes = []
    price.currency = "EUR"
    price_factory.get_price_from_object.return_value = price
    variant = ProductVariant(id=uuid4(), name="x", price=4.0)

    _service(price_factory=price_factory).get_variant_pricing(variant)

    price_factory.get_price_from_object.assert_called_once_with(variant)
