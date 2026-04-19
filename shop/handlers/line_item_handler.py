"""ShopLineItemHandler — handles CUSTOM line items for shop products."""
import logging
import uuid

from vbwd.events.line_item_registry import (
    ILineItemHandler,
    LineItemContext,
    LineItemResult,
)
from vbwd.models.enums import LineItemType

logger = logging.getLogger(__name__)


class ShopLineItemHandler(ILineItemHandler):
    """Handles CUSTOM line items where metadata.plugin == 'shop'."""

    def __init__(self, session_factory, event_bus=None):
        self._session_factory = session_factory
        self._event_bus = event_bus

    def can_handle_line_item(self, line_item, context: LineItemContext) -> bool:
        return (
            line_item.item_type == LineItemType.CUSTOM
            and (line_item.extra_data or {}).get("plugin") == "shop"
        )

    def activate_line_item(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        """On payment capture: commit stock + create order."""
        extra = line_item.extra_data or {}

        try:
            from plugins.shop.shop.services.stock_service import StockService
            from plugins.shop.shop.repositories.warehouse_stock_repository import (
                WarehouseStockRepository,
            )
            from plugins.shop.shop.repositories.stock_block_repository import (
                StockBlockRepository,
            )
            from plugins.shop.shop.repositories.order_repository import (
                OrderRepository,
            )
            from plugins.shop.shop.models.order import Order, OrderStatus
            from plugins.shop.shop.models.order_item import OrderItem
            from vbwd.extensions import db

            session = db.session
            stock_service = StockService(
                WarehouseStockRepository(session),
                StockBlockRepository(session),
                self._event_bus,
            )

            # Commit stock blocks for this invoice
            session_id = str(context.invoice.id)
            stock_service.commit_stock(session_id)

            # Create order
            order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
            order = Order(
                id=uuid.uuid4(),
                user_id=context.user_id,
                invoice_id=context.invoice.id,
                order_number=order_number,
                status=OrderStatus.CONFIRMED,
                subtotal=line_item.total_price,
                total_amount=line_item.total_price,
                currency=context.invoice.currency or "EUR",
            )
            session.add(order)
            session.flush()

            # Create order item
            order_item = OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                product_id=uuid.UUID(extra["product_id"]),
                variant_id=uuid.UUID(extra["variant_id"]) if extra.get("variant_id") else None,
                warehouse_id=uuid.UUID(extra["warehouse_id"]) if extra.get("warehouse_id") else None,
                quantity=extra.get("quantity", 1),
                unit_price=line_item.unit_price,
                total_price=line_item.total_price,
                product_snapshot={
                    "name": extra.get("product_name"),
                    "sku": extra.get("product_sku"),
                    "slug": extra.get("product_slug"),
                },
            )
            session.add(order_item)
            session.commit()

            # Write order_id back to line item metadata
            line_item.extra_data = {**extra, "order_id": str(order.id), "order_number": order_number}

            if self._event_bus:
                self._event_bus.publish(
                    "order.created",
                    {
                        "order_id": str(order.id),
                        "order_number": order_number,
                        "user_id": str(context.user_id),
                        "total": str(order.total_amount),
                    },
                )

            logger.info(
                "Ecommerce order %s created from invoice %s",
                order_number,
                context.invoice.id,
            )

            return LineItemResult(
                success=True,
                data={"order_id": str(order.id), "order_number": order_number},
            )

        except Exception as error:
            logger.error("ShopLineItemHandler.activate failed: %s", error)
            return LineItemResult.from_error(str(error))

    def reverse_line_item(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        """On refund: cancel order + restore stock."""
        extra = line_item.extra_data or {}
        order_id = extra.get("order_id")

        if not order_id:
            return LineItemResult(success=True, data={})

        try:
            from plugins.shop.shop.repositories.order_repository import (
                OrderRepository,
            )
            from plugins.shop.shop.services.stock_service import StockService
            from plugins.shop.shop.repositories.warehouse_stock_repository import (
                WarehouseStockRepository,
            )
            from plugins.shop.shop.repositories.stock_block_repository import (
                StockBlockRepository,
            )
            from plugins.shop.shop.models.order import OrderStatus
            from vbwd.extensions import db

            session = db.session
            order_repo = OrderRepository(session)
            order = order_repo.find_by_id(order_id)

            if order and order.status not in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
                order.status = OrderStatus.REFUNDED
                order_repo.save(order)

                # Restore stock for each order item
                stock_service = StockService(
                    WarehouseStockRepository(session),
                    StockBlockRepository(session),
                    self._event_bus,
                )
                for item in order.items:
                    if item.warehouse_id:
                        stock_service.restore_stock(
                            item.product_id, item.warehouse_id, item.quantity, item.variant_id
                        )

                if self._event_bus:
                    self._event_bus.publish(
                        "order.refunded",
                        {"order_id": str(order.id), "user_id": str(context.user_id)},
                    )

            return LineItemResult(success=True, data={"order_id": order_id})

        except Exception as error:
            logger.error("ShopLineItemHandler.reverse failed: %s", error)
            return LineItemResult.from_error(str(error))

    def restore_line_item(
        self, line_item, context: LineItemContext
    ) -> LineItemResult:
        """On refund reversal: re-confirm order + re-decrement stock."""
        extra = line_item.extra_data or {}
        order_id = extra.get("order_id")

        if not order_id:
            return LineItemResult(success=True, data={})

        try:
            from plugins.shop.shop.repositories.order_repository import (
                OrderRepository,
            )
            from plugins.shop.shop.models.order import OrderStatus
            from vbwd.extensions import db

            order_repo = OrderRepository(db.session)
            order = order_repo.find_by_id(order_id)

            if order and order.status == OrderStatus.REFUNDED:
                order.status = OrderStatus.CONFIRMED
                order_repo.save(order)

            return LineItemResult(success=True, data={"order_id": order_id})

        except Exception as error:
            logger.error("ShopLineItemHandler.restore failed: %s", error)
            return LineItemResult.from_error(str(error))
