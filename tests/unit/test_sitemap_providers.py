"""S154 P2 — shop sitemap providers (registry v2 contract), unit level.

The providers expose ``name`` / ``count()`` / ``page(offset, limit)`` over the
shop repositories (MagicMock here — no DB) and build entries through an injected
``entry_factory`` (cms's ``SitemapEntry`` in production), so shop source never
imports cms. Each provider follows its fe-admin switch: OFF → count 0, no rows,
and the repository is never queried.

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock

from plugins.shop.shop.sitemap_providers import (
    ShopCategorySitemapProvider,
    ShopProductSitemapProvider,
)

UPDATED_AT = datetime(2026, 11, 10, 9, 30, 0)


@dataclass
class _Entry:
    loc: str
    lastmod: Optional[str] = None


def _product_provider(repository, switch_on=True):
    return ShopProductSitemapProvider(
        repository_factory=lambda: repository,
        entry_factory=_Entry,
        switch_is_on=lambda: switch_on,
    )


def _category_provider(repository, switch_on=True):
    return ShopCategorySitemapProvider(
        repository_factory=lambda: repository,
        entry_factory=_Entry,
        switch_is_on=lambda: switch_on,
    )


def test_provider_names_are_stable_public_url_ids():
    assert ShopProductSitemapProvider.name == "shop-products"
    assert ShopCategorySitemapProvider.name == "shop-categories"


def test_product_count_is_the_active_product_count():
    repository = MagicMock()
    repository.count_active.return_value = 1_999_999

    assert _product_provider(repository).count() == 1_999_999


def test_product_page_builds_storefront_paths_with_lastmod():
    repository = MagicMock()
    repository.list_active_sitemap_rows.return_value = [
        ("blue-mug", UPDATED_AT),
        ("red-mug", None),
    ]

    entries = list(_product_provider(repository).page(100, 2))

    repository.list_active_sitemap_rows.assert_called_once_with(100, 2)
    assert entries == [
        _Entry(loc="/shop/product/blue-mug", lastmod=UPDATED_AT.isoformat()),
        _Entry(loc="/shop/product/red-mug", lastmod=None),
    ]


def test_product_switch_off_yields_nothing_and_never_queries():
    repository = MagicMock()

    provider = _product_provider(repository, switch_on=False)

    assert provider.count() == 0
    assert list(provider.page(0, 50_000)) == []
    repository.count_active.assert_not_called()
    repository.list_active_sitemap_rows.assert_not_called()


def test_category_count_and_page():
    repository = MagicMock()
    repository.count.return_value = 8
    repository.list_sitemap_rows.return_value = [("books", UPDATED_AT)]

    provider = _category_provider(repository)

    assert provider.count() == 8
    assert list(provider.page(0, 50_000)) == [
        _Entry(loc="/shop/category/books", lastmod=UPDATED_AT.isoformat())
    ]
    repository.list_sitemap_rows.assert_called_once_with(0, 50_000)


def test_category_switch_off_yields_nothing_and_never_queries():
    repository = MagicMock()

    provider = _category_provider(repository, switch_on=False)

    assert provider.count() == 0
    assert list(provider.page(0, 10)) == []
    repository.count.assert_not_called()
    repository.list_sitemap_rows.assert_not_called()


def test_seo_switch_defaults_products_on_categories_off():
    from plugins.shop import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["seo_index_products"] is True
    assert DEFAULT_CONFIG["seo_index_categories"] is False


def test_seo_switch_reads_the_live_runtime_config():
    from flask import Flask

    from plugins.shop.shop.services import plugin_config

    class _Store:
        def get_config(self, plugin_name):
            assert plugin_name == "shop"
            return {"seo_index_products": False, "seo_index_categories": True}

    app = Flask(__name__)
    with app.app_context():
        assert plugin_config.seo_indexing_enabled("seo_index_products") is True
        setattr(app, "config_store", _Store())
        assert plugin_config.seo_indexing_enabled("seo_index_products") is False
        assert plugin_config.seo_indexing_enabled("seo_index_categories") is True
