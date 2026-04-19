"""ProductReview domain model."""
import enum
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class ReviewStatus(enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProductReview(BaseModel):
    """User review of a product."""

    __tablename__ = "shop_product_review"

    product_id = db.Column(UUID(as_uuid=True), db.ForeignKey("shop_product.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("vbwd_user.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = db.Column(UUID(as_uuid=True), nullable=True)
    rating = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(255), nullable=True)
    body = db.Column(db.Text, nullable=True)
    status = db.Column(
        db.Enum(ReviewStatus, name="shop_reviewstatus", native_enum=True, create_constraint=False),
        nullable=False, default=ReviewStatus.PENDING, index=True,
    )
    is_verified_purchase = db.Column(db.Boolean, nullable=False, default=False)
    admin_response = db.Column(db.Text, nullable=True)
    helpful_count = db.Column(db.Integer, nullable=False, default=0)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "product_id": str(self.product_id),
            "user_id": str(self.user_id),
            "rating": self.rating,
            "title": self.title,
            "body": self.body,
            "status": self.status.value,
            "is_verified_purchase": self.is_verified_purchase,
            "admin_response": self.admin_response,
            "helpful_count": self.helpful_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
