"""WishlistItem domain model."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class WishlistItem(BaseModel):
    """User's wishlist item."""

    __tablename__ = "shop_wishlist_item"
    __table_args__ = (
        db.UniqueConstraint("user_id", "product_id", "variant_id", name="uq_wishlist_user_product_variant"),
    )

    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("vbwd_user.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("shop_product.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id = db.Column(UUID(as_uuid=True), db.ForeignKey("shop_product_variant.id", ondelete="CASCADE"), nullable=True)
    added_at = db.Column(db.DateTime, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "product_id": str(self.product_id),
            "variant_id": str(self.variant_id) if self.variant_id else None,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }
