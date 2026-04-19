"""Order repository."""
from typing import Optional, List
from uuid import UUID
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.order import Order, OrderStatus


class OrderRepository(BaseRepository[Order]):
    def __init__(self, session):
        super().__init__(session, Order)

    def find_by_order_number(self, order_number: str) -> Optional[Order]:
        return self._session.query(Order).filter_by(order_number=order_number).first()

    def find_by_invoice_id(self, invoice_id: UUID) -> Optional[Order]:
        return self._session.query(Order).filter_by(invoice_id=invoice_id).first()

    def find_by_user(
        self, user_id: UUID, page: int = 1, per_page: int = 20
    ) -> List[Order]:
        return (
            self._session.query(Order)
            .filter_by(user_id=user_id)
            .order_by(Order.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def find_by_status(
        self, status: OrderStatus, page: int = 1, per_page: int = 20
    ) -> List[Order]:
        return (
            self._session.query(Order)
            .filter_by(status=status)
            .order_by(Order.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def count_by_user(self, user_id: UUID) -> int:
        return self._session.query(Order).filter_by(user_id=user_id).count()
