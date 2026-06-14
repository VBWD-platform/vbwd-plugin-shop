"""Order domain model."""
import enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class OrderStatus(enum.Enum):
    """Order lifecycle status."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class Order(BaseModel):
    """E-commerce order — created when payment is captured."""

    __tablename__ = "shop_order"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("vbwd_user_invoice.id"),
        nullable=True,
        index=True,
    )
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    status = db.Column(
        db.Enum(
            OrderStatus,
            name="shop_orderstatus",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
    )

    shipping_address = db.Column(JSONB, nullable=True, default=dict)
    billing_address = db.Column(JSONB, nullable=True, default=dict)
    shipping_method = db.Column(db.String(100), nullable=True)
    # S85.1 (D4): money columns are full-precision doubles, never rounded in
    # code; the currency is the global ``default_currency`` (S84).
    shipping_cost = db.Column(db.Float, nullable=True, default=0)
    tracking_number = db.Column(db.String(255), nullable=True)
    tracking_url = db.Column(db.String(500), nullable=True)

    subtotal = db.Column(db.Float, nullable=False, default=0)
    tax_amount = db.Column(db.Float, nullable=False, default=0)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    items = db.relationship(
        "OrderItem",
        backref="order",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "order_number": self.order_number,
            "status": self.status.value,
            "shipping_address": self.shipping_address,
            "billing_address": self.billing_address,
            "shipping_method": self.shipping_method,
            "shipping_cost": str(self.shipping_cost) if self.shipping_cost else "0",
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
            "subtotal": str(self.subtotal),
            "tax_amount": str(self.tax_amount),
            "total_amount": str(self.total_amount),
            "notes": self.notes,
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Order(number='{self.order_number}', status={self.status.value})>"
