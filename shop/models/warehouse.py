"""Warehouse domain model."""
from sqlalchemy.dialects.postgresql import JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Warehouse(BaseModel):
    """Physical or virtual warehouse for stock tracking."""

    __tablename__ = "shop_warehouse"

    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    address = db.Column(JSONB, nullable=True, default=dict)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    stock_items = db.relationship(
        "WarehouseStock",
        backref="warehouse",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "address": self.address,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Warehouse(name='{self.name}', default={self.is_default})>"
