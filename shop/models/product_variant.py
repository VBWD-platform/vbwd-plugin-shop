"""ProductVariant domain model — size, color, etc."""
from sqlalchemy.dialects.postgresql import UUID, JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class ProductVariant(BaseModel):
    """Product variant — each combination of attributes (size + color) is a variant."""

    __tablename__ = "shop_product_variant"

    product_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("shop_product.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=True, index=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    price_float = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Numeric(10, 3), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    attributes = db.Column(JSONB, nullable=False, default=dict)
    image_url = db.Column(db.String(500), nullable=True)

    @property
    def raw_price(self) -> float:
        """The variant's price as a float (``Priceable`` member, S85/S101.0).

        A variant prices via the core ``PriceFactory`` like any sellable: its own
        ``price`` when set, otherwise it falls back to the parent product's price
        so a variant without an explicit override still resolves a price.
        """
        if self.price is not None:
            return float(self.price)
        if self.price_float is not None:
            return float(self.price_float)
        product = getattr(self, "product", None)
        return float(product.price) if product and product.price is not None else 0.0

    @property
    def taxes(self):
        """Inherit the parent product's assigned taxes (``Priceable`` member).

        Tax is a product-level concern (a pack inherits its product's tax
        treatment); the variant carries only its own price. Empty when the
        product is not loaded.
        """
        product = getattr(self, "product", None)
        return getattr(product, "taxes", None) or []

    @property
    def price_display_mode(self):
        """Inherit the parent product's display-mode override (S72.4)."""
        product = getattr(self, "product", None)
        return getattr(product, "price_display_mode", None)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "product_id": str(self.product_id),
            "name": self.name,
            "sku": self.sku,
            "price": str(self.price) if self.price else None,
            "price_float": self.price_float,
            "weight": str(self.weight) if self.weight else None,
            "is_active": self.is_active,
            "attributes": self.attributes,
            "image_url": self.image_url,
        }

    def __repr__(self) -> str:
        return f"<ProductVariant(name='{self.name}', sku='{self.sku}')>"
