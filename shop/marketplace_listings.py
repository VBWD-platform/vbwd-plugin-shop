"""Marketplace vendor-listings provider for the shop vertical.

The central ``marketplace`` plugin owns a registry that aggregates a user's
listings across every enabled vertical (its admin "what does this user sell?"
view). Shop contributes a provider that returns the raw ``Product`` dicts a
given vendor owns — mirroring the ``vendor_list_products`` GET route.

This module never imports the marketplace plugin (the money path stays
decoupled — see ``test_vendor_mode_contract``); the actual registration onto the
marketplace registry is a guarded, soft import done in the plugin's ``on_enable``
(``plugins/shop/__init__.py``), so the per-plugin isolated CI (shop without
marketplace) still enables cleanly. Core names nothing here.
"""
from typing import List
from uuid import UUID

# The listing ``type`` id shop contributes — mirrors the marketplace
# ``LISTING_TYPE_CATALOG`` and the fe-user ``ListingType`` for products.
SHOP_LISTING_TYPE_ID = "product"


def vendor_listings_provider(user_id: UUID) -> List[dict]:
    """Return the raw ``Product`` dicts owned by ``user_id`` (the vendor).

    Resolves ``db.session`` and constructs the repository lazily at call time
    (the call happens inside a Flask request), so there is no app-context work
    at import time. Reuses exactly what ``vendor_list_products`` reads.
    """
    from vbwd.extensions import db
    from plugins.shop.shop.repositories.product_repository import ProductRepository

    products = ProductRepository(db.session).find_by_vendor_id(user_id)
    return [product.to_dict() for product in products]
