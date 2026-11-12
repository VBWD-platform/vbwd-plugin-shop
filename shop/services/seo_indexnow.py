"""IndexNow ping for shop entities (S154 D4) — cms stays an optional dependency.

Calls cms's stable ``ping_indexnow_urls`` seam through a lazy import (a silent
no-op when cms is absent or not enabled), mirroring the optional-dependency
pattern ``_register_sitemap_providers`` already uses for the sitemap registry
(D3). The public path is built from the SAME templates shop's own sitemap
providers use (``PRODUCT_PATH_TEMPLATE`` / ``CATEGORY_PATH_TEMPLATE``, DRY —
never recomputed), and each ping is gated by that entity type's own fe-admin
"indexable" switch (D7) — the identical switch the sitemap provider checks.

The ``notify_*_changed`` functions cover one row; the ``notify_products_changed``
batch form is for the existing bulk routes (bulk delete/activate/deactivate) so
N row changes become ONE IndexNow POST instead of N (D4 batching) — cms's
``ping_indexnow_urls`` already accepts a path list for exactly this.
"""
import logging
from typing import Iterable, List

from plugins.shop.shop.constants import CATEGORY_PATH_TEMPLATE, PRODUCT_PATH_TEMPLATE
from plugins.shop.shop.services.plugin_config import (
    SEO_INDEX_CATEGORIES_KEY,
    SEO_INDEX_PRODUCTS_KEY,
    seo_indexing_enabled,
)

logger = logging.getLogger(__name__)


def _import_ping_indexnow_urls():
    """cms's stable IndexNow ping seam (raises ``ImportError`` without cms)."""
    from plugins.cms.src.services.seo_wiring import ping_indexnow_urls

    return ping_indexnow_urls


def _ping_many(paths: List[str]) -> None:
    """Best-effort: a missing cms or a failing ping never breaks the caller."""
    try:
        ping_indexnow_urls = _import_ping_indexnow_urls()
    except ImportError:
        return
    try:
        ping_indexnow_urls(paths)
    except Exception as exc:  # pragma: no cover - defensive, best-effort
        logger.warning("[shop.indexnow] ping failed for %s: %s", paths, exc)


def notify_product_changed(slug: str) -> None:
    """Ping IndexNow of a changed product's public URL (switch-gated, D7)."""
    if not slug or not seo_indexing_enabled(SEO_INDEX_PRODUCTS_KEY):
        return
    _ping_many([PRODUCT_PATH_TEMPLATE.format(slug=slug)])


def notify_category_changed(slug: str) -> None:
    """Ping IndexNow of a changed category's public URL (switch-gated, D7)."""
    if not slug or not seo_indexing_enabled(SEO_INDEX_CATEGORIES_KEY):
        return
    _ping_many([CATEGORY_PATH_TEMPLATE.format(slug=slug)])


def notify_products_changed(slugs: Iterable[str]) -> None:
    """Ping IndexNow once for several changed products (switch-gated, D7).

    For the existing bulk routes (bulk delete / activate / deactivate): one
    HTTP request in, one IndexNow POST out, never one per row.
    """
    if not seo_indexing_enabled(SEO_INDEX_PRODUCTS_KEY):
        return
    paths = [PRODUCT_PATH_TEMPLATE.format(slug=slug) for slug in (slugs or []) if slug]
    if not paths:
        return
    _ping_many(paths)
