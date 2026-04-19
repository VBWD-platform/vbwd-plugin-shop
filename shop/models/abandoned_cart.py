"""AbandonedCart domain model."""
import enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class AbandonedCartStatus(enum.Enum):
    DETECTED = "DETECTED"
    REMINDER_1_SENT = "REMINDER_1_SENT"
    REMINDER_2_SENT = "REMINDER_2_SENT"
    REMINDER_3_SENT = "REMINDER_3_SENT"
    RECOVERED = "RECOVERED"
    EXPIRED = "EXPIRED"


class AbandonedCart(BaseModel):
    """Tracks abandoned shopping carts for recovery emails."""

    __tablename__ = "shop_abandoned_cart"

    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("vbwd_user.id", ondelete="CASCADE"), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=True)
    invoice_id = db.Column(UUID(as_uuid=True), nullable=True, index=True)
    cart_data = db.Column(JSONB, nullable=False, default=list)
    cart_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    status = db.Column(
        db.Enum(AbandonedCartStatus, name="shop_abandonedcartstatus", native_enum=True, create_constraint=False),
        nullable=False, default=AbandonedCartStatus.DETECTED, index=True,
    )
    detected_at = db.Column(db.DateTime, nullable=False)
    reminder_1_at = db.Column(db.DateTime, nullable=True)
    reminder_2_at = db.Column(db.DateTime, nullable=True)
    reminder_3_at = db.Column(db.DateTime, nullable=True)
    recovered_at = db.Column(db.DateTime, nullable=True)
    recovery_invoice_id = db.Column(UUID(as_uuid=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "email": self.email,
            "cart_total": str(self.cart_total),
            "currency": self.currency,
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "recovered_at": self.recovered_at.isoformat() if self.recovered_at else None,
            "cart_data": self.cart_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
