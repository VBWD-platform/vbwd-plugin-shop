"""WarehouseStock domain model — stock per product (or variant) per warehouse."""
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class WarehouseStock(BaseModel):
    """Stock level for a product or variant in a specific warehouse."""

    __tablename__ = "shop_warehouse_stock"
    __table_args__ = (
        db.UniqueConstraint(
            "warehouse_id", "product_id", "variant_id",
            name="uq_warehouse_product_variant",
        ),
    )

    warehouse_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_warehouse.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product_variant.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0)
    reserved = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=10)

    @property
    def available(self) -> int:
        """Available = quantity - reserved."""
        return max(0, self.quantity - self.reserved)

    @property
    def is_low_stock(self) -> bool:
        return self.available <= self.low_stock_threshold

    @property
    def is_out_of_stock(self) -> bool:
        return self.available <= 0

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "warehouse_id": str(self.warehouse_id),
            "product_id": str(self.product_id),
            "variant_id": str(self.variant_id) if self.variant_id else None,
            "quantity": self.quantity,
            "reserved": self.reserved,
            "available": self.available,
            "low_stock_threshold": self.low_stock_threshold,
            "is_low_stock": self.is_low_stock,
            "is_out_of_stock": self.is_out_of_stock,
        }

    def __repr__(self) -> str:
        return (
            f"<WarehouseStock(product={self.product_id}, "
            f"warehouse={self.warehouse_id}, qty={self.quantity}, reserved={self.reserved})>"
        )
