"""Shop product search provider (cross-entity search seam).

Contributes shop products to the core ``search_provider_registry`` so the
``/search`` bot (and any future search surface) can find them. Searches only
public, non-personal fields (name / description / sku via the repository's own
``search``) and re-resolves a tapped hit by slug. The public fe-user detail
route is ``/shop/product/<slug>``.
"""
from __future__ import annotations

from typing import List, Optional

from vbwd.services.search import SearchHit

ENTITY_TYPE = "shop_product"
ENTITY_LABEL = "Shop"
DETAIL_URL_TEMPLATE = "/shop/product/{slug}"


class ShopProductSearchProvider:
    """A ``SearchProvider`` for active shop products."""

    entity_type: str = ENTITY_TYPE
    entity_label: str = ENTITY_LABEL

    def search(self, query: str, *, limit: int = 5) -> List[SearchHit]:
        if not query or not query.strip():
            return []
        products = self._repository().search(query, page=1, per_page=limit)
        return [self._to_hit(product) for product in products]

    def get_detail(self, key: str) -> Optional[SearchHit]:
        repository = self._repository()
        product = repository.find_by_slug(key)
        if product is None:
            product = self._find_by_id(repository, key)
        if product is None:
            return None
        return self._to_hit(product)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _repository(self):
        from vbwd.extensions import db
        from plugins.shop.shop.repositories.product_repository import (
            ProductRepository,
        )

        return ProductRepository(db.session)

    @staticmethod
    def _find_by_id(repository, key: str):
        try:
            return repository.find_by_id(key)
        except Exception:  # noqa: BLE001 — a non-uuid key is simply "not found"
            return None

    def _to_hit(self, product) -> SearchHit:
        return SearchHit(
            entity_type=self.entity_type,
            entity_label=self.entity_label,
            key=product.slug,
            title=product.name,
            snippet=self._snippet(product.description),
            url=DETAIL_URL_TEMPLATE.format(slug=product.slug),
            price=_format_price(product.price),
        )

    @staticmethod
    def _snippet(description: Optional[str], *, max_length: int = 160) -> str:
        if not description:
            return ""
        text = description.strip()
        if len(text) <= max_length:
            return text
        return text[: max_length - 1].rstrip() + "…"


def _format_price(amount: Optional[float]) -> Optional[str]:
    """A best-effort display string ``"<amount> <currency>"`` (no client math)."""
    if amount is None:
        return None
    from vbwd.services.core_settings_store import get_default_currency

    # Reads the operating currency (file-backed; degrades to the schema default
    # on its own — never a call-site literal, never raises).
    currency = get_default_currency()
    return f"{float(amount):.2f} {currency}"
