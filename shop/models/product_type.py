"""Product type domain model (S116.1).

A product type is a **named, additive cluster of custom fields** layered on the
universal base product. It carries NO behaviour columns — fields only. A product
references at most one type via ``Product.product_type_slug`` (nullable; ``NULL``
= the simple default product, base fields only).

``product_type_fields`` is a list of field descriptors, each shaped like a
plugin admin-config field::

    {
        "slug": "download_url",
        "type": "url",
        "label": "Download URL",
        "required": false,
        "options": [],        # for select / multiselect
        "help": null,
        "sort_order": 0
    }

``source`` governs editability:
    - ``"plugin"`` — registered/reconciled from code; the owning plugin owns the
      field cluster, so the admin UI treats it as read-only.
    - ``"admin"`` — created via the UI, fully editable.
"""
from sqlalchemy.dialects.postgresql import JSONB
from vbwd.extensions import db
from vbwd.models.base import BaseModel

# The two provenance values for ``ProductType.source``. ``plugin`` rows are
# reconciled from a code registry and are read-only in the admin UI; ``admin``
# rows are UI-created and fully editable.
PRODUCT_TYPE_SOURCE_PLUGIN = "plugin"
PRODUCT_TYPE_SOURCE_ADMIN = "admin"
PRODUCT_TYPE_SOURCES = (PRODUCT_TYPE_SOURCE_PLUGIN, PRODUCT_TYPE_SOURCE_ADMIN)


class ProductType(BaseModel):
    """A named cluster of custom fields layered on the base product."""

    __tablename__ = "shop_product_type"

    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # The additive field cluster — a list of field descriptors (see module
    # docstring). May be ``[]`` (a type with no extra fields).
    product_type_fields = db.Column(JSONB, nullable=False, default=list)

    source = db.Column(
        db.String(16),
        nullable=False,
        default=PRODUCT_TYPE_SOURCE_ADMIN,
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "product_type_fields": self.product_type_fields or [],
            "source": self.source,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<ProductType(slug='{self.slug}', source='{self.source}')>"
