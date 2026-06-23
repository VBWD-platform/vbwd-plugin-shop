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

    def _register_data_exchangers(self) -> None:
        """Register the shop entity exchangers into the data-exchange seam.

        Core declares none of these (it stays agnostic); the plugin adds them on
        enable through the shared ``db.session`` so shop products and
        (export-only) orders appear on the generic Settings → Import/Export page.
        Clear-safe: re-registering replaces by key (per-test app re-enable).
        """
        import logging

        try:
            from vbwd.extensions import db
            from plugins.shop.shop.services.data_exchange.shop_exchangers import (
                register_shop_exchangers,
            )

            register_shop_exchangers(db.session)
        except Exception as exchanger_error:
            logging.getLogger(__name__).warning(
                "[shop] Failed to register data exchangers: %s", exchanger_error
            )

    def on_enable(self):
        import plugins.shop.shop.models  # noqa: F401

        # S09 — register the plugin's repositories with the DI container so
        # routes / handlers / other plugins can resolve them via
        # container.shop_<name>_repository(). Without this, the 2026-03-27
        # outage class returns the moment something calls
        # current_app.container.shop_product_repository().
        from flask import current_app

        from vbwd.plugins.di_helpers import register_repositories
        from plugins.shop.shop.repositories.order_item_repository import (
            OrderItemRepository,
        )
        from plugins.shop.shop.repositories.order_repository import OrderRepository
        from plugins.shop.shop.repositories.product_category_repository import (
            ProductCategoryRepository,
        )
        from plugins.shop.shop.repositories.product_repository import (
            ProductRepository,
        )
        from plugins.shop.shop.repositories.product_variant_repository import (
            ProductVariantRepository,
        )
        from plugins.shop.shop.repositories.stock_block_repository import (
            StockBlockRepository,
        )
        from plugins.shop.shop.repositories.warehouse_repository import (
            WarehouseRepository,
        )
        from plugins.shop.shop.repositories.warehouse_stock_repository import (
            WarehouseStockRepository,
        )

        container = getattr(current_app, "container", None)
        if container is not None:
            register_repositories(
                container,
                {
                    "shop_product_repository": ProductRepository,
                    "shop_product_variant_repository": ProductVariantRepository,
                    "shop_product_category_repository": ProductCategoryRepository,
                    "shop_order_repository": OrderRepository,
                    "shop_order_item_repository": OrderItemRepository,
                    "shop_warehouse_repository": WarehouseRepository,
                    "shop_warehouse_stock_repository": WarehouseStockRepository,
                    "shop_stock_block_repository": StockBlockRepository,
                },
            )

        self._register_data_exchangers()

        # S77 — make products addressable by the generic tags / custom-fields
        # framework. Registering the entity type lets the core value endpoints
        # (GET|PUT /admin/shop_product/<id>/{tags,custom-fields}) return 200
        # (gated by shop.products.manage) instead of 404.
        from vbwd.services.entity_type_registry import (
            EntityTypeRegistration,
            register_entity_type,
        )

        register_entity_type(
            EntityTypeRegistration("shop_product", "Product", "shop.products.manage")
        )

        # S88 — contribute the shop catalog seed to ``flask reset-demo`` through
        # the agnostic demo-data registry (core imports no shop model).
        from vbwd.services.demo_data_registry import register_catalog_seeder
        from plugins.shop.shop.demo_seed import seed_catalog

        register_catalog_seeder(seed_catalog)

        # Cross-entity search seam — contribute shop products to the agnostic
        # search registry so the /search bot can find them (idempotent: register
        # replaces by entity_type). Core names no shop vocabulary.
        from vbwd.services.search import search_provider_registry
        from plugins.shop.shop.search_provider import ShopProductSearchProvider

        search_provider_registry.register(ShopProductSearchProvider())

    def on_disable(self):
        from flask import current_app

        from vbwd.plugins.di_helpers import unregister_repositories

        container = getattr(current_app, "container", None)
        if container is not None:
            unregister_repositories(
                container,
                [
                    "shop_product_repository",
                    "shop_product_variant_repository",
                    "shop_product_category_repository",
                    "shop_order_repository",
                    "shop_order_item_repository",
                    "shop_warehouse_repository",
                    "shop_warehouse_stock_repository",
                    "shop_stock_block_repository",
                ],
            )

        from vbwd.services.entity_type_registry import unregister_entity_type

        unregister_entity_type("shop_product")

        from vbwd.services.search import search_provider_registry

        search_provider_registry.unregister("shop_product")

    @property
    def admin_permissions(self):
        return [
            {"key": "shop.products.view", "label": "View products", "group": "Shop"},
            {
                "key": "shop.products.manage",
                "label": "Manage products",
                "group": "Shop",
            },
            {"key": "shop.orders.view", "label": "View orders", "group": "Shop"},
            {"key": "shop.orders.manage", "label": "Manage orders", "group": "Shop"},
            {"key": "shop.stock.manage", "label": "Manage stock", "group": "Shop"},
            {
                "key": "shop.categories.manage",
                "label": "Manage categories",
                "group": "Shop",
            },
            {
                "key": "shop.warehouses.manage",
                "label": "Manage warehouses",
                "group": "Shop",
            },
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

        handler = ShopLineItemHandler(session_factory=db.session, event_bus=event_bus)
        registry.register(handler)
        logger.info("[shop] ShopLineItemHandler registered")

    def register_event_handlers(self, event_bus):
        pass
