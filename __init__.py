"""Shop plugin — products, orders, stock, shipping."""
from vbwd.plugins.base import BasePlugin, PluginMetadata
from plugins.shop.shop.shipping_registry import ShippingMethodRegistry

# Module-level singleton — shipping provider plugins register here
_shipping_registry = ShippingMethodRegistry()


DEFAULT_CONFIG = {
    "currency": "EUR",
    "stock_block_ttl_minutes": 5,
    "low_stock_threshold_default": 10,
    "enable_warehouses": True,
    "enable_digital_products": True,
    "order_number_prefix": "ORD",
    "tax_included_in_price": True,
    "max_cart_items": 50,
    "guest_checkout_enabled": True,
}


class ShopPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="shop",
            version="0.1.0",
            author="VBWD",
            description="Shop — products, orders, stock management, shipping",
            dependencies=["email"],
        )

    def initialize(self, config=None):
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self):
        from plugins.shop.shop.routes import shop_bp

        return shop_bp

    def get_url_prefix(self) -> str:
        return ""

    def on_enable(self):
        import plugins.shop.shop.models  # noqa: F401

    def on_disable(self):
        pass

    @property
    def admin_permissions(self):
        return [
            {"key": "shop.products.view", "label": "View products", "group": "Shop"},
            {"key": "shop.products.manage", "label": "Manage products", "group": "Shop"},
            {"key": "shop.orders.view", "label": "View orders", "group": "Shop"},
            {"key": "shop.orders.manage", "label": "Manage orders", "group": "Shop"},
            {"key": "shop.stock.manage", "label": "Manage stock", "group": "Shop"},
            {"key": "shop.categories.manage", "label": "Manage categories", "group": "Shop"},
            {"key": "shop.warehouses.manage", "label": "Manage warehouses", "group": "Shop"},
            {"key": "shop.configure", "label": "Shop settings", "group": "Shop"},
        ]

    def register_line_item_handlers(self, registry):
        import logging

        logger = logging.getLogger(__name__)

        from flask import current_app

        container = getattr(current_app, "container", None)
        if not container:
            logger.warning("[shop] No container — cannot register line item handler")
            return

        from vbwd.extensions import db
        from vbwd.events.bus import event_bus

        from plugins.shop.shop.handlers.line_item_handler import (
            ShopLineItemHandler,
        )

        handler = ShopLineItemHandler(
            session_factory=db.session, event_bus=event_bus
        )
        registry.register(handler)
        logger.info("[shop] ShopLineItemHandler registered")

    def register_event_handlers(self, event_bus):
        pass
