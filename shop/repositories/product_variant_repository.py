"""ProductVariant repository (S101.0).

Data access for shop ``ProductVariant`` rows. Variants are pack/strength/form
SKUs hanging off a ``Product``; any caller authors them through the
``ProductVariantService`` + admin CRUD API, never by touching the model
directly. The repository stays vertical-agnostic — it knows nothing about any
downstream module.
"""
from typing import List, Optional
from uuid import UUID

from vbwd.repositories.base import BaseRepository

from plugins.shop.shop.models.product_variant import ProductVariant


class ProductVariantRepository(BaseRepository[ProductVariant]):
    def __init__(self, session):
        super().__init__(session, ProductVariant)

    def list_for_product(self, product_id: UUID) -> List[ProductVariant]:
        """Every variant of a product, ordered by ``sort_order`` then name."""
        return (
            self._session.query(ProductVariant)
            .filter_by(product_id=product_id)
            .order_by(ProductVariant.sort_order, ProductVariant.name)
            .all()
        )

    def find_by_sku(self, sku: str) -> Optional[ProductVariant]:
        return self._session.query(ProductVariant).filter_by(sku=sku).first()

    def next_sort_order(self, product_id: UUID) -> int:
        """The sort_order to append a new variant at the end of the list."""
        existing = self.list_for_product(product_id)
        return (max((variant.sort_order for variant in existing), default=-1)) + 1
