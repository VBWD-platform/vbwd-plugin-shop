"""Stock service — blocking, committing, releasing, restoring stock."""
import logging
from datetime import timedelta
from uuid import UUID

from vbwd.utils.datetime_utils import utcnow
from plugins.shop.shop.models.stock_block import StockBlock, StockBlockStatus
from plugins.shop.shop.repositories.warehouse_stock_repository import (
    WarehouseStockRepository,
)
from plugins.shop.shop.repositories.stock_block_repository import (
    StockBlockRepository,
)

logger = logging.getLogger(__name__)


class InsufficientStockError(Exception):
    """Raised when requested quantity exceeds available stock."""

    pass


class StockService:
    def __init__(
        self,
        warehouse_stock_repository: WarehouseStockRepository,
        stock_block_repository: StockBlockRepository,
        event_bus=None,
    ):
        self._stock_repo = warehouse_stock_repository
        self._block_repo = stock_block_repository
        self._event_bus = event_bus

    def get_available(self, product_id: UUID, variant_id: UUID | None = None) -> int:
        return self._stock_repo.get_total_available(product_id, variant_id)

    def block_stock(
        self,
        product_id: UUID,
        quantity: int,
        session_id: str,
        ttl_minutes: int = 5,
        variant_id: UUID | None = None,
    ) -> StockBlock:
        """Reserve stock for checkout. Raises InsufficientStockError if unavailable."""
        warehouse_stock = self._stock_repo.find_best_warehouse(
            product_id, quantity, variant_id
        )
        if not warehouse_stock or warehouse_stock.available < quantity:
            available = self.get_available(product_id, variant_id)
            raise InsufficientStockError(
                f"Insufficient stock: requested {quantity}, available {available}"
            )

        warehouse_stock.reserved += quantity
        self._stock_repo.save(warehouse_stock)

        from uuid import uuid4

        block = StockBlock(
            id=uuid4(),
            product_id=product_id,
            variant_id=variant_id,
            warehouse_id=warehouse_stock.warehouse_id,
            session_id=session_id,
            quantity=quantity,
            status=StockBlockStatus.ACTIVE,
            expires_at=utcnow() + timedelta(minutes=ttl_minutes),
        )
        self._block_repo.save(block)

        if self._event_bus:
            self._event_bus.publish(
                "stock.blocked",
                {
                    "product_id": str(product_id),
                    "quantity": quantity,
                    "session_id": session_id,
                    "expires_at": block.expires_at.isoformat(),
                },
            )

        return block

    def commit_stock(self, session_id: str) -> int:
        """Convert blocks to permanent decrement on payment success."""
        blocks = self._block_repo.find_active_by_session(session_id)
        committed_count = 0

        for block in blocks:
            block.status = StockBlockStatus.COMMITTED

            warehouse_stock = self._stock_repo.find_by_product_and_warehouse(
                block.product_id, block.warehouse_id, block.variant_id
            )
            if warehouse_stock:
                warehouse_stock.reserved -= block.quantity
                warehouse_stock.quantity -= block.quantity
                self._stock_repo.save(warehouse_stock)

            committed_count += 1

            if self._event_bus:
                self._event_bus.publish(
                    "stock.committed",
                    {
                        "product_id": str(block.product_id),
                        "quantity": block.quantity,
                        "session_id": session_id,
                    },
                )

        return committed_count

    def release_stock(self, session_id: str) -> int:
        """Release blocks on timeout or cancellation."""
        blocks = self._block_repo.find_active_by_session(session_id)
        released_count = 0

        for block in blocks:
            block.status = StockBlockStatus.RELEASED

            warehouse_stock = self._stock_repo.find_by_product_and_warehouse(
                block.product_id, block.warehouse_id, block.variant_id
            )
            if warehouse_stock:
                warehouse_stock.reserved = max(
                    0, warehouse_stock.reserved - block.quantity
                )
                self._stock_repo.save(warehouse_stock)

            released_count += 1

            if self._event_bus:
                self._event_bus.publish(
                    "stock.released",
                    {
                        "product_id": str(block.product_id),
                        "quantity": block.quantity,
                        "session_id": session_id,
                        "reason": "timeout",
                    },
                )

        return released_count

    def restore_stock(
        self,
        product_id: UUID,
        warehouse_id: UUID,
        quantity: int,
        variant_id: UUID | None = None,
    ) -> None:
        """Restore stock on refund."""
        warehouse_stock = self._stock_repo.find_by_product_and_warehouse(
            product_id, warehouse_id, variant_id
        )
        if warehouse_stock:
            warehouse_stock.quantity += quantity
            self._stock_repo.save(warehouse_stock)

            if self._event_bus:
                self._event_bus.publish(
                    "stock.restored",
                    {
                        "product_id": str(product_id),
                        "quantity": quantity,
                    },
                )

    def cleanup_expired_blocks(self) -> int:
        """Scheduler job: release blocks past their TTL."""
        expired_blocks = self._block_repo.find_expired()
        released_count = 0

        for block in expired_blocks:
            block.status = StockBlockStatus.EXPIRED

            warehouse_stock = self._stock_repo.find_by_product_and_warehouse(
                block.product_id, block.warehouse_id, block.variant_id
            )
            if warehouse_stock:
                warehouse_stock.reserved = max(
                    0, warehouse_stock.reserved - block.quantity
                )
                self._stock_repo.save(warehouse_stock)

            released_count += 1

        if released_count:
            logger.info("[shop] Released %d expired stock blocks", released_count)

        return released_count
