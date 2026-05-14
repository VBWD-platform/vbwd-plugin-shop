"""Product domain model."""
from sqlalchemy.dialects.postgresql import JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class Product(BaseModel):
    """E-commerce product."""

    __tablename__ = "shop_product"

    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    sku = db.Column(db.String(100), unique=True, nullable=True, index=True)

    price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    price_float = db.Column(db.Float, nullable=False, default=0.0)

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_digital = db.Column(db.Boolean, nullable=False, default=False)
    has_variants = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    weight = db.Column(db.Numeric(10, 3), nullable=True)
    dimensions = db.Column(JSONB, nullable=True, default=dict)
    product_metadata = db.Column("product_metadata", JSONB, nullable=True, default=dict)
    tax_class = db.Column(db.String(50), nullable=False, default="standard")

    # Relationships
    images = db.relationship(
        "ProductImage",
        backref="product",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order",
    )
    variants = db.relationship(
        "ProductVariant",
        backref="product",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ProductVariant.sort_order",
    )

    @property
    def primary_image_url(self) -> str | None:
        """Get the primary image URL."""
        for image in self.images:
            if image.is_primary:
                return image.url
        return self.images[0].url if self.images else None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "sku": self.sku,
            "price": str(self.price),
            "currency": self.currency,
            "price_float": self.price_float,
            "is_active": self.is_active,
            "is_digital": self.is_digital,
            "has_variants": self.has_variants,
            "weight": str(self.weight) if self.weight else None,
            "dimensions": self.dimensions,
            "tax_class": self.tax_class,
            "primary_image_url": self.primary_image_url,
            "images": [img.to_dict() for img in self.images],
            "variants": [v.to_dict() for v in self.variants]
            if self.has_variants
            else [],
            "categories": self._serialize_categories(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def _serialize_categories(self) -> list:
        try:
            cats = getattr(self, "categories", None)
            if cats is None:
                return []
            return [{"id": str(c.id), "name": c.name, "slug": c.slug} for c in cats]
        except Exception:
            return []

    def __repr__(self) -> str:
        return f"<Product(slug='{self.slug}', price={self.price})>"
