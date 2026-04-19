"""Warehouse repository."""
from typing import Optional, List
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.warehouse import Warehouse


class WarehouseRepository(BaseRepository[Warehouse]):
    def __init__(self, session):
        super().__init__(session, Warehouse)

    def find_by_slug(self, slug: str) -> Optional[Warehouse]:
        return self._session.query(Warehouse).filter_by(slug=slug).first()

    def find_active(self) -> List[Warehouse]:
        return (
            self._session.query(Warehouse)
            .filter_by(is_active=True)
            .order_by(Warehouse.sort_order)
            .all()
        )

    def find_default(self) -> Optional[Warehouse]:
        return self._session.query(Warehouse).filter_by(is_default=True).first()
