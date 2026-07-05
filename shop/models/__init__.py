"""Ecommerce models — import all to register with SQLAlchemy."""
from plugins.shop.shop.models.product import Product  # noqa: F401
from plugins.shop.shop.models.product_type import ProductType  # noqa: F401
from plugins.shop.shop.models.product_variant import ProductVariant  # noqa: F401
from plugins.shop.shop.models.product_category import ProductCategory  # noqa: F401
from plugins.shop.shop.models.product_image import ProductImage  # noqa: F401
from plugins.shop.shop.models.warehouse import Warehouse  # noqa: F401
from plugins.shop.shop.models.warehouse_stock import WarehouseStock  # noqa: F401
from plugins.shop.shop.models.stock_block import StockBlock  # noqa: F401
from plugins.shop.shop.models.order import Order  # noqa: F401
from plugins.shop.shop.models.order_item import OrderItem  # noqa: F401

# Discount, Coupon, CouponUsage moved to plugins/discount/ plugin
from plugins.shop.shop.models.review import ProductReview  # noqa: F401
from plugins.shop.shop.models.wishlist import WishlistItem  # noqa: F401
from plugins.shop.shop.models.abandoned_cart import AbandonedCart  # noqa: F401
