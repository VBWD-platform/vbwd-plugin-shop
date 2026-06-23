"""Checkout-validation registry (S101.0) — shop-owned, vertical-agnostic.

Shop's cart-checkout route runs every registered ``CheckoutValidator`` against
the cart BEFORE it blocks stock or creates the invoice. A validator returns a
rejection reason to fail the checkout closed, or ``None`` to allow it.

This is the seam a downstream module uses to enforce its own purchase gates
server-side WITHOUT editing shop's checkout logic or core. Shop ships zero
validators; it merely runs whatever is registered. The registry names no
vertical, so the shop-agnostic oracle stays green.
"""
from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class CheckoutValidator(Protocol):
    """A pluggable cart gate. Implementations live in downstream modules."""

    def validate_cart(self, *, items: list, user_id) -> Optional[str]:
        """Return a rejection reason (str) to block the checkout, else ``None``.

        Args:
            items: The cart line dicts (``product_id`` / ``quantity`` /
                optional ``variant_id``) exactly as the checkout route received
                them.
            user_id: The authenticated buyer's id (may be ``None`` for guests).
        """
        ...


class CheckoutValidationError(ValueError):
    """A registered validator rejected the cart (carries the reason code)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CheckoutValidationRegistry:
    """Holds the registered validators; replaces by class name (idempotent)."""

    def __init__(self) -> None:
        self._validators: dict = {}

    def register(self, validator: CheckoutValidator) -> None:
        """Add (or replace) a validator, keyed by its class name."""
        self._validators[type(validator).__name__] = validator

    def unregister(self, validator_name: str) -> None:
        self._validators.pop(validator_name, None)

    def clear(self) -> None:
        self._validators.clear()

    def get_all(self) -> List[CheckoutValidator]:
        return list(self._validators.values())

    def validate(self, *, items: list, user_id) -> None:
        """Run every validator; raise on the first rejection (fail-closed)."""
        for validator in self._validators.values():
            reason = validator.validate_cart(items=items, user_id=user_id)
            if reason:
                raise CheckoutValidationError(reason)


# Module-level singleton — downstream modules register their gates here on
# enable, mirroring the shop ``_shipping_registry`` pattern.
_checkout_validation_registry = CheckoutValidationRegistry()


def get_checkout_validation_registry() -> CheckoutValidationRegistry:
    return _checkout_validation_registry
