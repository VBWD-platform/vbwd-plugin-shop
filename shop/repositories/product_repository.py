"""Product repository."""
from typing import Optional, List
from sqlalchemy import or_
from vbwd.repositories.base import BaseRepository
from plugins.shop.shop.models.product import Product


class ProductRepository(BaseRepository[Product]):
    def __init__(self, session):
        super().__init__(session, Product)

    def find_by_slug(self, slug: str) -> Optional[Product]:
        return self._session.query(Product).filter_by(slug=slug).first()

    def find_by_sku(self, sku: str) -> Optional[Product]:
        return self._session.query(Product).filter_by(sku=sku).first()

    def find_active(self, page: int = 1, per_page: int = 20) -> List[Product]:
        return (
            self._session.query(Product)
            .filter_by(is_active=True)
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def count_active(self) -> int:
        return self._session.query(Product).filter_by(is_active=True).count()

    def search(self, query: str, page: int = 1, per_page: int = 20) -> List[Product]:
        pattern = f"%{query}%"
        return (
            self._session.query(Product)
            .filter(
                Product.is_active.is_(True),
                or_(
                    Product.name.ilike(pattern),
                    Product.description.ilike(pattern),
                    Product.sku.ilike(pattern),
                ),
            )
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

    def find_by_category_slug(
        self, category_slug: str, page: int = 1, per_page: int = 20
    ) -> List[Product]:
        from plugins.shop.shop.models.product_category import (
            ProductCategory,
            shop_product_category_link,
        )

        return (
            self._session.query(Product)
            .join(
                shop_product_category_link,
                Product.id == shop_product_category_link.c.product_id,
            )
            .join(
                ProductCategory,
                ProductCategory.id == shop_product_category_link.c.category_id,
            )
            .filter(ProductCategory.slug == category_slug, Product.is_active.is_(True))
            .order_by(Product.sort_order, Product.name)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
