"""WarehouseStock repository."""
from typing import Optional, List
from uuid import UUID
from sqlalchemy import func
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.warehouse_stock import WarehouseStock


class WarehouseStockRepository(BaseRepository[WarehouseStock]):
    def __init__(self, session):
        super().__init__(session, WarehouseStock)

    def find_by_product(
        self, product_id: UUID, variant_id: UUID | None = None
    ) -> List[WarehouseStock]:
        query = self._session.query(WarehouseStock).filter_by(product_id=product_id)
        if variant_id:
            query = query.filter_by(variant_id=variant_id)
        else:
            query = query.filter(WarehouseStock.variant_id.is_(None))
        return query.all()

    def find_by_product_and_warehouse(
        self,
        product_id: UUID,
        warehouse_id: UUID,
        variant_id: UUID | None = None,
    ) -> Optional[WarehouseStock]:
        query = self._session.query(WarehouseStock).filter_by(
            product_id=product_id, warehouse_id=warehouse_id
        )
        if variant_id:
            query = query.filter_by(variant_id=variant_id)
        else:
            query = query.filter(WarehouseStock.variant_id.is_(None))
        return query.first()

    def get_total_available(
        self, product_id: UUID, variant_id: UUID | None = None
    ) -> int:
        query = self._session.query(
            func.coalesce(func.sum(WarehouseStock.quantity - WarehouseStock.reserved), 0)
        ).filter_by(product_id=product_id)
        if variant_id:
            query = query.filter_by(variant_id=variant_id)
        else:
            query = query.filter(WarehouseStock.variant_id.is_(None))
        result = query.scalar()
        return max(0, int(result or 0))

    def find_best_warehouse(
        self, product_id: UUID, quantity: int, variant_id: UUID | None = None
    ) -> Optional[WarehouseStock]:
        """Find the warehouse with the most available stock for this product."""
        stocks = self.find_by_product(product_id, variant_id)
        best = None
        best_available = 0
        for stock in stocks:
            if stock.available >= quantity and stock.available > best_available:
                best = stock
                best_available = stock.available
        return best
