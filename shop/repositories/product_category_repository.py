"""ProductCategory repository."""
from typing import Optional, List
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.product_category import ProductCategory


class ProductCategoryRepository(BaseRepository[ProductCategory]):
    def __init__(self, session):
        super().__init__(session, ProductCategory)

    def find_by_slug(self, slug: str) -> Optional[ProductCategory]:
        return self._session.query(ProductCategory).filter_by(slug=slug).first()

    def find_root_categories(self) -> List[ProductCategory]:
        return (
            self._session.query(ProductCategory)
            .filter_by(parent_id=None)
            .order_by(ProductCategory.sort_order, ProductCategory.name)
            .all()
        )

    def find_all_sorted(self) -> List[ProductCategory]:
        return (
            self._session.query(ProductCategory)
            .order_by(ProductCategory.sort_order, ProductCategory.name)
            .all()
        )
