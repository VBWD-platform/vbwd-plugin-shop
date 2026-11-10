"""Shop sitemap providers (cms sitemap registry v2, S154 P2).

Two providers, one per public URL family: active products
(``/shop/product/<slug>``) and categories (``/shop/category/<slug>``). Each is
DB-paged — ``count()`` is a SQL COUNT of the public filter and ``page()`` reads
one ``ORDER BY id`` OFFSET/LIMIT window of ``(slug, updated_at)`` columns — so a
2M-product catalogue never loads more than one sitemap chunk.

The duck-typed contract (``name`` / ``count()`` / ``page(offset, limit)``) lives
in cms; shop never imports cms here. The entry type (cms ``SitemapEntry``) is
injected by the plugin wiring root, which registers these providers only when
cms is enabled (optional dependency, D3). Each provider follows its fe-admin
switch, read live per call: OFF → ``count()`` 0 and no rows.
"""
from datetime import datetime
from typing import Any, Callable, List, Optional, Tuple

from plugins.shop.shop.constants import CATEGORY_PATH_TEMPLATE, PRODUCT_PATH_TEMPLATE
from plugins.shop.shop.repositories.product_category_repository import (
    ProductCategoryRepository,
)
from plugins.shop.shop.repositories.product_repository import ProductRepository
from plugins.shop.shop.services.plugin_config import (
    SEO_INDEX_CATEGORIES_KEY,
    SEO_INDEX_PRODUCTS_KEY,
    seo_indexing_enabled,
)

SitemapRow = Tuple[str, Optional[datetime]]


class _ShopSitemapProvider:
    """Switch gate + entry building shared by the shop providers."""

    name: str
    path_template: str

    def __init__(
        self,
        repository_factory: Callable[[], Any],
        entry_factory: Callable[..., Any],
        switch_is_on: Callable[[], bool],
    ) -> None:
        self._repository_factory = repository_factory
        self._entry_factory = entry_factory
        self._switch_is_on = switch_is_on

    def count(self) -> int:
        if not self._switch_is_on():
            return 0
        return self._count_rows(self._repository_factory())

    def page(self, offset: int, limit: int) -> List[Any]:
        if not self._switch_is_on():
            return []
        return [
            self._entry_factory(
                loc=self.path_template.format(slug=slug),
                lastmod=updated_at.isoformat() if updated_at else None,
            )
            for slug, updated_at in self._page_rows(
                self._repository_factory(), offset, limit
            )
        ]

    def _count_rows(self, repository: Any) -> int:
        raise NotImplementedError

    def _page_rows(self, repository: Any, offset: int, limit: int) -> List[SitemapRow]:
        raise NotImplementedError


class ShopProductSitemapProvider(_ShopSitemapProvider):
    """Active (storefront-listed) products."""

    name = "shop-products"
    path_template = PRODUCT_PATH_TEMPLATE

    def _count_rows(self, repository: ProductRepository) -> int:
        return repository.count_active()

    def _page_rows(
        self, repository: ProductRepository, offset: int, limit: int
    ) -> List[SitemapRow]:
        return repository.list_active_sitemap_rows(offset, limit)


class ShopCategorySitemapProvider(_ShopSitemapProvider):
    """Every product category (all are public)."""

    name = "shop-categories"
    path_template = CATEGORY_PATH_TEMPLATE

    def _count_rows(self, repository: ProductCategoryRepository) -> int:
        return repository.count()

    def _page_rows(
        self, repository: ProductCategoryRepository, offset: int, limit: int
    ) -> List[SitemapRow]:
        return repository.list_sitemap_rows(offset, limit)


def build_sitemap_providers(
    session_factory: Callable[[], Any], entry_factory: Callable[..., Any]
) -> List[_ShopSitemapProvider]:
    """The shop providers wired to live sessions and the fe-admin switches."""
    return [
        ShopProductSitemapProvider(
            repository_factory=lambda: ProductRepository(session_factory()),
            entry_factory=entry_factory,
            switch_is_on=lambda: seo_indexing_enabled(SEO_INDEX_PRODUCTS_KEY),
        ),
        ShopCategorySitemapProvider(
            repository_factory=lambda: ProductCategoryRepository(session_factory()),
            entry_factory=entry_factory,
            switch_is_on=lambda: seo_indexing_enabled(SEO_INDEX_CATEGORIES_KEY),
        ),
    ]
