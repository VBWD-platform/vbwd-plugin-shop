"""ProductVariantService (S101.0) — author pack/strength/form variants.

The shop's variant-authoring seam: create / update / delete / reorder / toggle
a product's variants programmatically. Pricing is delegated to the core
``PriceFactory`` (variants are ``Priceable`` via their stored ``price``); stock
lives in the existing variant-aware ``WarehouseStock`` paths and is not touched
here. The service is vertical-agnostic so a downstream module can drive it
through the admin API without shop ever learning about that module.
"""
from typing import List, Optional
from uuid import UUID, uuid4

from plugins.shop.shop.models.product_variant import ProductVariant
from plugins.shop.shop.repositories.product_variant_repository import (
    ProductVariantRepository,
)


class VariantNotFoundError(ValueError):
    """Raised when a variant id does not belong to the given product."""


class DuplicateVariantSkuError(ValueError):
    """Raised when a variant SKU collides with an existing variant."""


# The mutable attributes a caller may set on create/update. Kept explicit so an
# unknown payload key is ignored rather than silently written to the model.
_EDITABLE_ATTRIBUTES = (
    "name",
    "sku",
    "weight",
    "is_active",
    "sort_order",
    "attributes",
    "image_url",
)


class ProductVariantService:
    """CRUD + reorder/toggle for a product's variants."""

    def __init__(self, variant_repository: ProductVariantRepository, price_factory):
        """Initialize the service.

        Args:
            variant_repository: Data access for ``ProductVariant`` rows.
            price_factory: The core ``PriceFactory`` (single price-math entry
                point) — used to compute a variant's net/tax/gross pricing.
        """
        self._variant_repository = variant_repository
        self._price_factory = price_factory

    def list_variants(self, product_id: UUID) -> List[ProductVariant]:
        return self._variant_repository.list_for_product(product_id)

    def create_variant(self, product_id: UUID, data: dict) -> ProductVariant:
        """Create a new variant for a product (appended to the end of the list)."""
        if not data.get("name"):
            raise ValueError("Variant name is required")

        sku = data.get("sku")
        if sku and self._variant_repository.find_by_sku(sku) is not None:
            raise DuplicateVariantSkuError(f"Variant with sku '{sku}' already exists")

        variant = ProductVariant(
            id=uuid4(),
            product_id=product_id,
            name=data["name"],
            sku=sku,
            price=data.get("price"),
            price_float=self._coerce_price_float(data.get("price")),
            weight=data.get("weight"),
            is_active=data.get("is_active", True),
            sort_order=data.get(
                "sort_order", self._variant_repository.next_sort_order(product_id)
            ),
            attributes=data.get("attributes") or {},
            image_url=data.get("image_url"),
        )
        return self._variant_repository.save(variant)

    def update_variant(
        self, product_id: UUID, variant_id: UUID, data: dict
    ) -> ProductVariant:
        """Update a variant's editable attributes."""
        variant = self._require_variant(product_id, variant_id)

        if "sku" in data and data["sku"]:
            existing = self._variant_repository.find_by_sku(data["sku"])
            if existing is not None and str(existing.id) != str(variant_id):
                raise DuplicateVariantSkuError(
                    f"Variant with sku '{data['sku']}' already exists"
                )

        for attribute in _EDITABLE_ATTRIBUTES:
            if attribute in data:
                setattr(variant, attribute, data[attribute])
        if "price" in data:
            variant.price = data["price"]
            variant.price_float = self._coerce_price_float(data["price"])

        return self._variant_repository.save(variant)

    def delete_variant(self, product_id: UUID, variant_id: UUID) -> None:
        variant = self._require_variant(product_id, variant_id)
        self._variant_repository.delete(variant.id)

    def reorder_variants(
        self, product_id: UUID, ordered_variant_ids: List[UUID]
    ) -> List[ProductVariant]:
        """Set ``sort_order`` to match the given id sequence (0-based)."""
        variants_by_id = {
            str(variant.id): variant
            for variant in self._variant_repository.list_for_product(product_id)
        }
        for position, variant_id in enumerate(ordered_variant_ids):
            variant = variants_by_id.get(str(variant_id))
            if variant is None:
                raise VariantNotFoundError(
                    f"Variant {variant_id} does not belong to product {product_id}"
                )
            variant.sort_order = position
            self._variant_repository.save(variant)
        return self._variant_repository.list_for_product(product_id)

    def toggle_variant(self, product_id: UUID, variant_id: UUID) -> ProductVariant:
        """Flip a variant's ``is_active`` flag."""
        variant = self._require_variant(product_id, variant_id)
        variant.is_active = not variant.is_active
        return self._variant_repository.save(variant)

    def get_variant_pricing(self, variant: ProductVariant) -> dict:
        """The variant's net/tax/gross block computed via the ``PriceFactory``.

        The variant carries its own ``price`` (a ``Priceable``); when absent the
        caller falls back to the product's price. Delegated to the factory so no
        new tax/round path is introduced (S85/S96).
        """
        from vbwd.pricing.price_payload import build_pricing_block

        price = self._price_factory.get_price_from_object(variant)
        return build_pricing_block(price)

    # --- internals ---
    def _require_variant(self, product_id: UUID, variant_id: UUID) -> ProductVariant:
        variant = self._variant_repository.find_by_id(variant_id)
        if variant is None or str(variant.product_id) != str(product_id):
            raise VariantNotFoundError(
                f"Variant {variant_id} does not belong to product {product_id}"
            )
        return variant

    @staticmethod
    def _coerce_price_float(price) -> Optional[float]:
        if price is None:
            return None
        return float(price)
