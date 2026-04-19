"""StockBlock repository."""
from typing import List
from uuid import UUID
from vbwd.repositories.base import BaseRepository
from vbwd.utils.datetime_utils import utcnow
from plugins.shop.shop.models.stock_block import StockBlock, StockBlockStatus


class StockBlockRepository(BaseRepository[StockBlock]):
    def __init__(self, session):
        super().__init__(session, StockBlock)

    def find_active_by_session(self, session_id: str) -> List[StockBlock]:
        return (
            self._session.query(StockBlock)
            .filter_by(session_id=session_id, status=StockBlockStatus.ACTIVE)
            .all()
        )

    def find_expired(self) -> List[StockBlock]:
        """Find active blocks past their expiry time."""
        return (
            self._session.query(StockBlock)
            .filter(
                StockBlock.status == StockBlockStatus.ACTIVE,
                StockBlock.expires_at < utcnow(),
            )
            .all()
        )

    def find_active_by_product(
        self, product_id: UUID, variant_id: UUID | None = None
    ) -> List[StockBlock]:
        query = self._session.query(StockBlock).filter_by(
            product_id=product_id, status=StockBlockStatus.ACTIVE
        )
        if variant_id:
            query = query.filter_by(variant_id=variant_id)
        return query.all()
