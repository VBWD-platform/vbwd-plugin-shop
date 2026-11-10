"""ProductCategory repository."""
from datetime import datetime
from typing import Optional, List, Tuple
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

    def list_sitemap_rows(
        self, offset: int, limit: int
    ) -> List[Tuple[str, Optional[datetime]]]:
        """``(slug, updated_at)`` of every category, one stable ``id``-ordered page.

        Column-only select: no ``children`` / ``products`` relationship loads.
        Every category is public (the storefront lists the whole tree).
        """
        return [
            (slug, updated_at)
            for slug, updated_at in self._session.query(
                ProductCategory.slug, ProductCategory.updated_at
            )
            .order_by(ProductCategory.id)
            .offset(offset)
            .limit(limit)
        ]
