"""Product pricing service — computes net/tax/gross via the core ``PriceFactory``.

S85.2 (D1): all price math is delegated to the core ``PriceFactory`` (resolved
via the DI container at the route layer). The service no longer re-derives tax —
it reads ``Price.netto/brutto/taxes`` and serialises them. The global
``prices_mode_in_db`` setting (NETTO vs BRUTTO) is honoured by the factory, so
the same stored ``price`` double yields net-on-top or net-extracted depending on
the mode. The display-mode pair (S72.4) is orthogonal and carried as before.
"""
from vbwd.pricing.display_mode import display_mode_fields
from vbwd.pricing.price_payload import build_pricing_block

from plugins.shop.shop.models.product import Product


class ProductPricingService:
    """Compute a product's net/tax/gross pricing through the ``PriceFactory``."""

    def __init__(self, price_factory):
        """Initialize ProductPricingService.

        Args:
            price_factory: The core ``PriceFactory`` (single price-math entry
                point, D1).
        """
        self._price_factory = price_factory

    def get_product_pricing_payload(self, product: Product) -> dict:
        """Return the API-ready ``pricing`` block computed via the factory.

        The block carries the backward-compatible breakdown
        (``net_amount`` / ``tax_amount`` / ``gross_amount`` / ``tax_rate`` /
        ``taxes``), the serialized computed ``price`` object, and the
        display-mode pair (S72.4).
        """
        price = self._price_factory.get_price_from_object(product)
        payload = build_pricing_block(price)
        payload.update(display_mode_fields(product))
        return payload
