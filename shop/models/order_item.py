"""OrderItem domain model."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class OrderItem(BaseModel):
    """Line item within an order — tracks product, quantity, and refund state."""

    __tablename__ = "shop_order_item"

    order_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product.id"),
        nullable=False,
        index=True,
    )
    variant_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product_variant.id"),
        nullable=True,
    )
    warehouse_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_warehouse.id"),
        nullable=True,
    )
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    is_refunded = db.Column(db.Boolean, nullable=False, default=False)
    refunded_quantity = db.Column(db.Integer, nullable=False, default=0)
    product_snapshot = db.Column(JSONB, nullable=True, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "order_id": str(self.order_id),
            "product_id": str(self.product_id),
            "variant_id": str(self.variant_id) if self.variant_id else None,
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price),
            "total_price": str(self.total_price),
            "is_refunded": self.is_refunded,
            "refunded_quantity": self.refunded_quantity,
            "product_snapshot": self.product_snapshot,
        }

    def __repr__(self) -> str:
        return f"<OrderItem(product={self.product_id}, qty={self.quantity})>"
