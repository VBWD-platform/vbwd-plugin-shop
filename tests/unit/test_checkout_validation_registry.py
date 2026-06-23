"""S101.0 — checkout-validation registry unit tests (shop-owned seam).

Contract:
- ``register`` adds validators (replace-by-class-name, idempotent).
- ``validate`` runs every validator and raises ``CheckoutValidationError`` with
  the first rejection reason (fail-closed); passes when all return ``None``.
- shop ships no validators of its own (the registry is empty by default).
"""
import pytest

from plugins.shop.shop.checkout_validation_registry import (
    CheckoutValidationError,
    CheckoutValidationRegistry,
)


class _AllowValidator:
    def validate_cart(self, *, items, user_id):
        return None


class _RejectValidator:
    def validate_cart(self, *, items, user_id):
        return "prescription_required"


def test_empty_registry_allows():
    registry = CheckoutValidationRegistry()
    registry.validate(items=[{"product_id": "x"}], user_id="u")  # no raise


def test_rejecting_validator_raises_with_reason():
    registry = CheckoutValidationRegistry()
    registry.register(_RejectValidator())
    with pytest.raises(CheckoutValidationError) as caught:
        registry.validate(items=[{"product_id": "x"}], user_id="u")
    assert caught.value.reason == "prescription_required"


def test_register_replaces_by_class_name():
    registry = CheckoutValidationRegistry()
    registry.register(_AllowValidator())
    registry.register(_AllowValidator())
    assert len(registry.get_all()) == 1


def test_unregister_and_clear():
    registry = CheckoutValidationRegistry()
    registry.register(_RejectValidator())
    registry.unregister("_RejectValidator")
    registry.validate(items=[], user_id=None)  # no raise after removal
    registry.register(_RejectValidator())
    registry.clear()
    registry.validate(items=[], user_id=None)
