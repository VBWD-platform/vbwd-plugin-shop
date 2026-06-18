"""ProductCategory domain model — hierarchical product grouping."""
from __future__ import annotations
from typing import TYPE_CHECKING, List
from sqlalchemy.orm import Mapped, relationship
from vbwd.extensions import db
from vbwd.models.base import BaseModel

if TYPE_CHECKING:
    from plugins.shop.shop.models.product import Product

# M2M junction table: category <-> product
shop_product_category_link = db.Table(
    "shop_product_category_link",
    db.Column(
        "category_id",
        db.UUID,
        db.ForeignKey("shop_product_category.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "product_id",
        db.UUID,
        db.ForeignKey("shop_product.id", ondelete="CASCADE"),
        primary_key=True,
        # ``product_id`` is the SECOND column of the composite PK, so the PK index
        # cannot serve a ``WHERE product_id = ?`` probe. Without this standalone
        # index the ``ON DELETE CASCADE`` to this table seq-scans the link heap
        # once per deleted product → O(N²) on a bulk product delete (the S89 t3
        # load-test reset hang). Every sibling FK→shop_product table already has
        # such an index; this was the lone gap. Mirrored by migration
        # 20260617_shop_link_product_id_idx for existing DBs.
        index=True,
    ),
)


class ProductCategory(BaseModel):
    """Hierarchical product category."""

    __tablename__ = "shop_product_category"

    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    parent_id = db.Column(
        db.UUID,
        db.ForeignKey("shop_product_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    children: Mapped[List[ProductCategory]] = relationship(
        "ProductCategory",
        backref=db.backref("parent", remote_side="ProductCategory.id"),
        lazy="selectin",
    )

    products: Mapped[List[Product]] = relationship(
        "Product",
        secondary=shop_product_category_link,
        backref=db.backref("categories", lazy="selectin"),
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "image_url": self.image_url,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "sort_order": self.sort_order,
            "product_count": len(self.products),
            "children": [child.to_dict() for child in self.children],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<ProductCategory(slug='{self.slug}')>"
