"""Product-type repository (S116.1)."""
from typing import List, Optional

from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.product_type import ProductType


class ProductTypeRepository(BaseRepository[ProductType]):
    def __init__(self, session):
        super().__init__(session, ProductType)

    def find_by_slug(self, slug: str) -> Optional[ProductType]:
        return self._session.query(ProductType).filter_by(slug=slug).first()

    def find_active(self) -> List[ProductType]:
        """Active types, ordered by name for a deterministic list."""
        return (
            self._session.query(ProductType)
            .filter_by(is_active=True)
            .order_by(ProductType.name)
            .all()
        )

    def list_all(self) -> List[ProductType]:
        """Every type (active or not), ordered by name — the admin list."""
        return self._session.query(ProductType).order_by(ProductType.name).all()
