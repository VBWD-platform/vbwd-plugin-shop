"""Product domain model."""
from typing import Optional

from sqlalchemy.dialects.postgresql import JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel

# S72.4: a per-product netto/brutto price-display override. ``None`` inherits the
# global ``prices_display_mode`` core setting; ``"netto"``/``"brutto"`` override
# it. Kept in sync with the core ``PRICES_DISPLAY_MODES`` enum.
PRICE_DISPLAY_MODE_OVERRIDES = ("netto", "brutto")


def validate_price_display_mode(value: Optional[str]) -> Optional[str]:
    """Return ``value`` if it is a valid override, else raise ``ValueError``.

    ``None`` (inherit the global setting) and the two enum values are accepted;
    any other value is rejected so the admin route can map it to a 400.
    """
    if value is None or value in PRICE_DISPLAY_MODE_OVERRIDES:
        return value
    raise ValueError(
        "price_display_mode must be one of "
        f"{(None,) + PRICE_DISPLAY_MODE_OVERRIDES}, got {value!r}"
    )


# Many-to-many join to the CORE tax catalog (``vbwd_tax``). The ``tax_id`` FK
# uses ``ON DELETE RESTRICT`` so deleting a tax that is assigned to a product is
# rejected by the database (S72.3) rather than silently dropping the link; the
# ``product_id`` FK uses ``ON DELETE CASCADE`` so deleting a product tidies its
# own links.
shop_product_tax = db.Table(
    "shop_product_tax",
    db.Column(
        "product_id",
        db.UUID,
        db.ForeignKey("shop_product.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tax_id",
        db.UUID,
        db.ForeignKey("vbwd_tax.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Product(BaseModel):
    """E-commerce product."""

    __tablename__ = "shop_product"

    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    sku = db.Column(db.String(100), unique=True, nullable=True, index=True)

    # S85.1 (D4/D5): the single price double (full precision, never rounded in
    # code); the currency is the global ``default_currency`` (S84).
    price = db.Column(db.Float, nullable=False, default=0)

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_digital = db.Column(db.Boolean, nullable=False, default=False)
    has_variants = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    weight = db.Column(db.Numeric(10, 3), nullable=True)
    dimensions = db.Column(JSONB, nullable=True, default=dict)
    product_metadata = db.Column("product_metadata", JSONB, nullable=True, default=dict)
    tax_class = db.Column(db.String(50), nullable=False, default="standard")

    # S72.4: per-product netto/brutto override. ``NULL`` inherits the global
    # ``prices_display_mode`` core setting; ``"netto"``/``"brutto"`` override it.
    price_display_mode = db.Column(db.String(8), nullable=True)

    # S116.1 — the product's type (a named additive field cluster). ``NULL`` is
    # the simple default product (base fields only). Soft-ref to
    # ``shop_product_type.slug`` — loose coupling, NOT a hard FK, so a disabled
    # type-owning plugin leaves a readable slug that simply renders no extra
    # cluster. ``type_field_values`` holds the per-product values keyed by the
    # type's field slugs (empty when there is no type).
    product_type_slug = db.Column(db.String(100), nullable=True, index=True)
    type_field_values = db.Column(JSONB, nullable=True, default=dict)

    # Vendor-mode (marketplace): the owning vendor's ``vbwd_user`` id. ``NULL``
    # is a platform-owned product. Indexed for the vendor's "my products" filter;
    # ``ON DELETE SET NULL`` so removing a user reverts their products to the
    # platform rather than deleting the catalog rows.
    vendor_id = db.Column(
        db.UUID,
        db.ForeignKey("vbwd_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    # Assigned core taxes (M2M). When present these take precedence over the
    # legacy ``tax_class`` string for pricing (S72.3).
    taxes = db.relationship(
        "Tax",
        secondary=shop_product_tax,
        lazy="selectin",
    )

    @property
    def raw_price(self) -> float:
        """The stored price as a float (the ``Priceable`` protocol member)."""
        return float(self.price) if self.price is not None else 0.0

    @property
    def primary_image_url(self) -> str | None:
        """Get the primary image URL."""
        for image in self.images:
            if image.is_primary:
                return image.url
        return self.images[0].url if self.images else None

    def to_dict(self) -> dict:
        taxes = self._serialize_taxes()
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "sku": self.sku,
            "price": self.raw_price,
            "is_active": self.is_active,
            "is_digital": self.is_digital,
            "has_variants": self.has_variants,
            "weight": str(self.weight) if self.weight else None,
            "dimensions": self.dimensions,
            "tax_class": self.tax_class,
            "price_display_mode": self.price_display_mode,
            "product_type_slug": self.product_type_slug,
            "type_field_values": self.type_field_values or {},
            "vendor_id": str(self.vendor_id) if self.vendor_id else None,
            "tax_ids": [tax["id"] for tax in taxes],
            "taxes": taxes,
            "primary_image_url": self.primary_image_url,
            "images": [img.to_dict() for img in self.images],
            "variants": [v.to_dict() for v in self.variants]
            if self.has_variants
            else [],
            "categories": self._serialize_categories(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def _serialize_taxes(self) -> list:
        """Serialize assigned core taxes to ``{id, code, name, rate}``."""
        taxes = getattr(self, "taxes", None) or []
        return [
            {
                "id": str(tax.id),
                "code": tax.code,
                "name": tax.name,
                "rate": str(tax.rate),
            }
            for tax in taxes
        ]

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
