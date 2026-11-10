"""S154 P2 — with cms enabled, the live sitemap lists shop's product chunk.

The app boots the way production does (manifest-enabled cms + shop; shop's
``on_enable`` registers its providers with cms's registry — no manual wiring
here). ``/sitemap.xml`` must list ``sitemap-shop-products-1.xml`` and that chunk
must contain a seeded active product's storefront URL (and not an inactive
one). Skipped when cms is absent or not enabled (the per-plugin CI clones shop
alone — cms is an optional dependency, D3).

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
from uuid import uuid4

import pytest

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.repositories.product_repository import ProductRepository
from vbwd.plugins.base import PluginStatus

PRODUCTS_CHUNK_PATH = "/sitemap-shop-products-1.xml"


@pytest.fixture
def cms_enabled(app):
    pytest.importorskip("plugins.cms.src.services.seo_registry")
    cms_plugin = app.plugin_manager.get_plugin("cms")
    if cms_plugin is None or cms_plugin.status != PluginStatus.ENABLED:
        pytest.skip("cms is not enabled in this environment (optional dependency)")


def _seed_product(db, is_active):
    slug = f"sitemap-route-{uuid4().hex[:10]}"
    return ProductRepository(db.session).save(
        Product(id=uuid4(), name=slug, slug=slug, price=4.0, is_active=is_active)
    )


def test_sitemap_index_lists_the_shop_products_chunk(db, app, cms_enabled):
    _seed_product(db, is_active=True)

    index_body = app.test_client().get("/sitemap.xml").get_data(as_text=True)

    assert f"{PRODUCTS_CHUNK_PATH}</loc>" in index_body


def test_products_chunk_lists_active_product_urls_only(db, app, cms_enabled):
    active = _seed_product(db, is_active=True)
    inactive = _seed_product(db, is_active=False)

    response = app.test_client().get(PRODUCTS_CHUNK_PATH)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f"/shop/product/{active.slug}</loc>" in body
    assert f"/shop/product/{inactive.slug}</loc>" not in body
