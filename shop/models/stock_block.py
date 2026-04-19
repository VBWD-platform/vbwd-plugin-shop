"""StockBlock domain model — temporary reservation during checkout."""
import enum
from sqlalchemy.dialects.postgresql import UUID
from vbwd.extensions import db
from vbwd.models.base import BaseModel
from vbwd.utils.datetime_utils import utcnow


class StockBlockStatus(enum.Enum):
    """Stock block lifecycle status."""

    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class StockBlock(BaseModel):
    """Temporary stock reservation during checkout.

    Created when user starts checkout. Expires after TTL if payment not completed.
    Committed when payment succeeds. Released on timeout or cancellation.
    """

    __tablename__ = "shop_stock_block"

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
    warehouse_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_warehouse.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = db.Column(db.String(255), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(
        db.Enum(
            StockBlockStatus,
            name="shop_stockblockstatus",
            native_enum=True,
            create_constraint=False,
        ),
        nullable=False,
        default=StockBlockStatus.ACTIVE,
        index=True,
    )

    @property
    def is_expired(self) -> bool:
        return self.status == StockBlockStatus.ACTIVE and utcnow() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "product_id": str(self.product_id),
            "variant_id": str(self.variant_id) if self.variant_id else None,
            "warehouse_id": str(self.warehouse_id),
            "session_id": self.session_id,
            "quantity": self.quantity,
            "status": self.status.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<StockBlock(product={self.product_id}, qty={self.quantity}, "
            f"status={self.status.value}, expires={self.expires_at})>"
        )
