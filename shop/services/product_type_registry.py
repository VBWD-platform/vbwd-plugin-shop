"""Product-type registry seam (S116.1) — code registry reconciled into the DB.

OCP: any plugin's ``on_enable`` calls :func:`register_product_type` with a
descriptor ``{slug, name, description, product_type_fields, source}``; on the
shop plugin's enable, :func:`reconcile_product_types` upserts every registered
descriptor into ``shop_product_type`` idempotently. This mirrors the platform's
established "code registry → reconcile to DB" shape (plugin manifest sync,
``line_item_registry``) — adding a type never edits shop.

Reconcile rules (idempotent):
    - unknown slug  → INSERT a ``source='plugin'`` row.
    - existing ``source='plugin'`` row → the owning plugin owns the cluster, so
      ``name`` / ``description`` / ``product_type_fields`` are overwritten.
    - existing ``source='admin'`` row → NEVER clobbered (admin owns it) — skipped.

Flask-free and free of any downstream-vertical import.
"""
import logging
from typing import Dict, List, Mapping, Optional

from plugins.shop.shop.models.product_type import (
    PRODUCT_TYPE_SOURCE_ADMIN,
    PRODUCT_TYPE_SOURCE_PLUGIN,
)

logger = logging.getLogger(__name__)

# The shop's own self-registered default cluster — proves the seam end to end.
# ``NULL`` (no type) stays the base-only default; ``digital`` is just another
# additive type, not a privileged default.
DIGITAL_TYPE_DESCRIPTOR = {
    "slug": "digital",
    "name": "Digital product",
    "description": "A downloadable/licensed product with delivery fields.",
    "product_type_fields": [
        {
            "slug": "download_url",
            "type": "url",
            "label": "Download URL",
            "required": False,
            "options": [],
            "help": "Where the buyer downloads the product after purchase.",
            "sort_order": 0,
        },
        {
            "slug": "license_key",
            "type": "string",
            "label": "License key",
            "required": False,
            "options": [],
            "help": None,
            "sort_order": 1,
        },
    ],
    "source": PRODUCT_TYPE_SOURCE_PLUGIN,
}


def _normalize_descriptor(descriptor: Mapping) -> dict:
    """Return a normalised descriptor dict; raise ``ValueError`` on a bad slug."""
    slug = descriptor.get("slug")
    if not slug:
        raise ValueError("product-type descriptor requires a non-empty 'slug'")
    return {
        "slug": slug,
        "name": descriptor.get("name") or slug,
        "description": descriptor.get("description"),
        "product_type_fields": list(descriptor.get("product_type_fields") or []),
        "source": descriptor.get("source") or PRODUCT_TYPE_SOURCE_PLUGIN,
    }


class ProductTypeRegistry:
    """In-memory registry of product-type descriptors keyed by slug."""

    def __init__(self) -> None:
        self._descriptors: Dict[str, dict] = {}

    def register(self, descriptor: Mapping) -> None:
        """Register (or replace) a descriptor by its slug — idempotent."""
        normalized = _normalize_descriptor(descriptor)
        self._descriptors[normalized["slug"]] = normalized

    def unregister(self, slug: str) -> None:
        """Remove a descriptor; no-op if absent (safe on repeat disable)."""
        self._descriptors.pop(slug, None)

    def clear(self) -> None:
        """Reset all descriptors (test teardown / plugin reload)."""
        self._descriptors.clear()

    def descriptors(self) -> List[dict]:
        """Every registered descriptor, ordered by slug (deterministic)."""
        return [self._descriptors[slug] for slug in sorted(self._descriptors)]


# Module-level singleton — plugins register at enable-time; shop reconciles.
product_type_registry = ProductTypeRegistry()


def register_product_type(descriptor: Mapping) -> None:
    """Register a product-type descriptor on the shared registry (convenience)."""
    product_type_registry.register(descriptor)


def reconcile_product_types(
    session, registry: Optional[ProductTypeRegistry] = None
) -> int:
    """Upsert every registered descriptor into ``shop_product_type`` (idempotent).

    Writes through and COMMITS ``session`` (a plugin writing DB from ``on_enable``
    must commit its own session; the test teardown otherwise rolls a flush-only
    write back). Returns the number of rows inserted (0 on a clean re-run).

    ``source='admin'`` rows are never clobbered; ``source='plugin'`` rows have
    their name / description / field cluster overwritten from the descriptor.
    """
    from uuid import uuid4

    from plugins.shop.shop.models.product_type import ProductType
    from plugins.shop.shop.repositories.product_type_repository import (
        ProductTypeRepository,
    )

    active_registry = registry if registry is not None else product_type_registry
    repository = ProductTypeRepository(session)
    inserted = 0
    for descriptor in active_registry.descriptors():
        existing = repository.find_by_slug(descriptor["slug"])
        if existing is None:
            session.add(
                ProductType(
                    id=uuid4(),
                    slug=descriptor["slug"],
                    name=descriptor["name"],
                    description=descriptor["description"],
                    product_type_fields=descriptor["product_type_fields"],
                    source=PRODUCT_TYPE_SOURCE_PLUGIN,
                    is_active=True,
                )
            )
            inserted += 1
            continue
        if existing.source == PRODUCT_TYPE_SOURCE_ADMIN:
            # Admin owns this row — never clobber a UI-created type.
            continue
        existing.name = descriptor["name"]
        existing.description = descriptor["description"]
        existing.product_type_fields = descriptor["product_type_fields"]
        repository.save(existing)
    session.commit()
    return inserted
