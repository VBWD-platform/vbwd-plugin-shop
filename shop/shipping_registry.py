"""Shipping method registry — shop plugin owns this.

Shipping provider plugins register here on enable.
The shop admin UI lists all registered methods.
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional

from vbwd.plugins.shipping_interface import (
    IShippingProvider,
    ShippingRate,
    ShipmentResult,
    TrackingInfo,
)

logger = logging.getLogger(__name__)


class PickupAtStoreProvider(IShippingProvider):
    """Built-in shipping method: customer picks up at store. Zero cost."""

    @property
    def slug(self) -> str:
        return "pickup-at-store"

    @property
    def name(self) -> str:
        return "Pick-up at Store"

    def calculate_rate(
        self,
        items: List[Dict],
        address: Dict,
        currency: str,
    ) -> List[ShippingRate]:
        return [
            ShippingRate(
                provider_slug=self.slug,
                name="Pick-up at Store",
                cost=Decimal("0.00"),
                currency=currency,
                estimated_days=0,
                description="Collect your order at our store",
            )
        ]

    def create_shipment(self, order: Dict) -> ShipmentResult:
        return ShipmentResult(
            success=True,
            tracking_number="",
            tracking_url="",
            label_url="",
        )

    def get_tracking(self, tracking_number: str) -> TrackingInfo:
        return TrackingInfo(status="ready_for_pickup")


class ShippingMethodRegistry:
    """Registry for shipping providers. Shop plugin owns this singleton."""

    def __init__(self) -> None:
        self._providers: Dict[str, IShippingProvider] = {}
        self._enabled: set[str] = set()
        # Built-in method always registered
        pickup = PickupAtStoreProvider()
        self._providers[pickup.slug] = pickup
        self._enabled.add(pickup.slug)

    def register(self, provider: IShippingProvider) -> None:
        self._providers[provider.slug] = provider
        self._enabled.add(provider.slug)
        logger.info(
            "[shop] Registered shipping provider: %s",
            provider.slug,
        )

    def unregister(self, slug: str) -> None:
        self._providers.pop(slug, None)
        self._enabled.discard(slug)

    def get_all(self) -> List[Dict]:
        """List all registered providers with status."""
        return [
            {
                "slug": slug,
                "name": provider.name,
                "enabled": slug in self._enabled,
                "is_builtin": slug == "pickup-at-store",
            }
            for slug, provider in self._providers.items()
        ]

    def get_enabled(self) -> List[IShippingProvider]:
        return [p for slug, p in self._providers.items() if slug in self._enabled]

    def get_provider(self, slug: str) -> Optional[IShippingProvider]:
        if slug in self._enabled:
            return self._providers.get(slug)
        return None

    def enable(self, slug: str) -> bool:
        if slug in self._providers:
            self._enabled.add(slug)
            return True
        return False

    def disable(self, slug: str) -> bool:
        if slug == "pickup-at-store":
            return False  # Built-in cannot be disabled
        self._enabled.discard(slug)
        return True

    @property
    def provider_count(self) -> int:
        return len(self._providers)
