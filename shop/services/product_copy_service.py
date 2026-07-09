"""ProductCopyService — duplicate ("make a copy") shop products.

The shop's product-duplication seam used by the admin bulk-copy route. A copy is
a fresh, always-inactive ``Product`` that carries over the source's scalar fields
and its OWNED children (variants + images, re-pointed at the new product), while
SHARED references (the tax M2M, the category M2M, the soft ``product_type_slug``
ref and ``vendor_id``) are re-pointed — never duplicated.

Unique columns (product ``slug``/``sku`` and variant ``sku``) are made unique with
a ``-copy`` / ``-copy-2`` … suffix, checked against the repository AND against the
values already reserved in the current bulk operation so two copies in one call
cannot collide. The service is vertical-agnostic — it knows nothing about any
downstream module.
"""
from copy import deepcopy
from typing import Callable, List, Optional, Set
from uuid import uuid4

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_image import ProductImage
from plugins.shop.shop.models.product_variant import ProductVariant
from plugins.shop.shop.repositories.product_repository import ProductRepository
from plugins.shop.shop.repositories.product_variant_repository import (
    ProductVariantRepository,
)

# Suffix appended to a copy's display name and the base of its unique slug/sku.
_COPY_NAME_SUFFIX = " (Copy)"
_COPY_UNIQUE_SUFFIX = "-copy"


class ProductCopyService:
    """Duplicate one or more products, each as a fresh inactive copy."""

    def __init__(
        self,
        product_repository: ProductRepository,
        variant_repository: ProductVariantRepository,
    ):
        self._product_repository = product_repository
        self._variant_repository = variant_repository

    def copy_products(self, product_ids: List) -> List[Product]:
        """Duplicate each existing product id; unknown ids are skipped.

        Returns the created copies in the order their source ids were given.
        Uniqueness of ``slug`` / ``sku`` is tracked across the whole call so two
        copies made in one request never collide with each other.
        """
        reserved_slugs: Set[str] = set()
        reserved_product_skus: Set[str] = set()
        reserved_variant_skus: Set[str] = set()

        copies: List[Product] = []
        for product_id in product_ids:
            source = self._product_repository.find_by_id(product_id)
            if source is None:
                continue
            copies.append(
                self._copy_product(
                    source,
                    reserved_slugs,
                    reserved_product_skus,
                    reserved_variant_skus,
                )
            )
        return copies

    def _copy_product(
        self,
        source: Product,
        reserved_slugs: Set[str],
        reserved_product_skus: Set[str],
        reserved_variant_skus: Set[str],
    ) -> Product:
        new_product = Product(
            id=uuid4(),
            name=f"{source.name}{_COPY_NAME_SUFFIX}",
            slug=self._unique_value(
                source.slug,
                reserved_slugs,
                self._product_repository.find_by_slug,
            ),
            sku=self._unique_optional_sku(
                source.sku,
                reserved_product_skus,
                self._product_repository.find_by_sku,
            ),
            description=source.description,
            price=source.price,
            # A copy is NEVER live — the admin activates it deliberately.
            is_active=False,
            has_variants=source.has_variants,
            sort_order=source.sort_order,
            weight=source.weight,
            dimensions=deepcopy(source.dimensions),
            product_metadata=deepcopy(source.product_metadata),
            tax_class=source.tax_class,
            price_display_mode=source.price_display_mode,
            # Soft ref — the type row is shared, only the slug string is copied.
            product_type_slug=source.product_type_slug,
            type_field_values=deepcopy(source.type_field_values),
            vendor_id=source.vendor_id,
        )

        # Shared references — re-point to the SAME rows, never duplicate them.
        new_product.taxes = list(source.taxes)
        new_product.categories = list(source.categories)

        # Owned children — duplicate as fresh rows re-pointed at the new product
        # (the relationship backref sets ``product_id`` on flush).
        new_product.images = [self._copy_image(image) for image in source.images]
        new_product.variants = [
            self._copy_variant(variant, reserved_variant_skus)
            for variant in source.variants
        ]

        return self._product_repository.save(new_product)

    def _copy_image(self, source: ProductImage) -> ProductImage:
        return ProductImage(
            id=uuid4(),
            url=source.url,
            alt=source.alt,
            sort_order=source.sort_order,
            is_primary=source.is_primary,
        )

    def _copy_variant(
        self, source: ProductVariant, reserved_variant_skus: Set[str]
    ) -> ProductVariant:
        return ProductVariant(
            id=uuid4(),
            name=source.name,
            sku=self._unique_optional_sku(
                source.sku,
                reserved_variant_skus,
                self._variant_repository.find_by_sku,
            ),
            price=source.price,
            price_float=source.price_float,
            weight=source.weight,
            is_active=source.is_active,
            sort_order=source.sort_order,
            attributes=deepcopy(source.attributes),
            image_url=source.image_url,
        )

    def _unique_optional_sku(
        self,
        source_sku: Optional[str],
        reserved: Set[str],
        exists: Callable[[str], Optional[object]],
    ) -> Optional[str]:
        """A unique ``-copy`` sku, or ``None`` when the source has no sku."""
        if source_sku is None:
            return None
        return self._unique_value(source_sku, reserved, exists)

    @staticmethod
    def _unique_value(
        base_value: str,
        reserved: Set[str],
        exists: Callable[[str], Optional[object]],
    ) -> str:
        """First free ``<base>-copy`` / ``<base>-copy-N`` value.

        Free means neither already reserved in this operation nor present in the
        repository. The chosen value is reserved before returning so a later copy
        in the same call cannot pick it again.
        """
        candidate = f"{base_value}{_COPY_UNIQUE_SUFFIX}"
        counter = 1
        while candidate in reserved or exists(candidate) is not None:
            counter += 1
            candidate = f"{base_value}{_COPY_UNIQUE_SUFFIX}-{counter}"
        reserved.add(candidate)
        return candidate
