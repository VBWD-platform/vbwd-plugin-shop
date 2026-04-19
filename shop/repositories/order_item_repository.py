"""OrderItem repository."""
from typing import List
from uuid import UUID
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.order_item import OrderItem


class OrderItemRepository(BaseRepository[OrderItem]):
    def __init__(self, session):
        super().__init__(session, OrderItem)

    def find_by_order(self, order_id: UUID) -> List[OrderItem]:
        return (
            self._session.query(OrderItem)
            .filter_by(order_id=order_id)
            .all()
        )

    def find_non_refunded_by_order(self, order_id: UUID) -> List[OrderItem]:
        return (
            self._session.query(OrderItem)
            .filter_by(order_id=order_id, is_refunded=False)
            .all()
        )
