"""S77 — the shop plugin registers its taggable / custom-field entity type.

Registering ``shop_product`` in ``on_enable`` is what lets the core value
endpoints (``GET|PUT /api/v1/admin/shop_product/<id>/{tags,custom-fields}``)
resolve the type and return 200 (gated ``shop.products.manage``) instead of 404.
If this registration regresses, the product edit page's Tags / Custom-fields
blocks silently 404.
"""
from vbwd.services.entity_type_registry import get_entity_type, is_registered


def test_shop_product_entity_type_registered(app):
    """The app fixture boots with shop enabled, so the type is registered."""
    assert is_registered("shop_product")
    registration = get_entity_type("shop_product")
    assert registration is not None
    assert registration.manage_permission == "shop.products.manage"
