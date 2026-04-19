"""ProductImage domain model."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class ProductImage(BaseModel):
    """Product image."""

    __tablename__ = "shop_product_image"

    product_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = db.Column(db.String(500), nullable=False)
    alt = db.Column(db.String(255), nullable=True, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "url": self.url,
            "alt": self.alt,
            "sort_order": self.sort_order,
            "is_primary": self.is_primary,
        }

    def __repr__(self) -> str:
        return f"<ProductImage(url='{self.url[:40]}...', primary={self.is_primary})>"
