"""S154 P2 — shop sitemap providers against a real PostgreSQL session.

Seeds through the repositories (no raw SQL) inside the rolled-back ``db``
fixture and asserts the registry-v2 contract at DB level: ``count()`` is the SQL
COUNT of the public filter (inactive products excluded), ``page()`` walks a
stable ``ORDER BY id`` sequence and honours offset/limit, and ``lastmod`` comes
from ``updated_at``.

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory
from plugins.shop.shop.repositories.product_category_repository import (
    ProductCategoryRepository,
)
from plugins.shop.shop.repositories.product_repository import ProductRepository
from plugins.shop.shop.sitemap_providers import (
    ShopCategorySitemapProvider,
    ShopProductSitemapProvider,
)

ALL_ROWS = 10_000_000


@dataclass
class _Entry:
    loc: str
    lastmod: Optional[str] = None


def _product_provider(db):
    return ShopProductSitemapProvider(
        repository_factory=lambda: ProductRepository(db.session),
        entry_factory=_Entry,
        switch_is_on=lambda: True,
    )


def _category_provider(db):
    return ShopCategorySitemapProvider(
        repository_factory=lambda: ProductCategoryRepository(db.session),
        entry_factory=_Entry,
        switch_is_on=lambda: True,
    )


def _seed_product(db, is_active):
    slug = f"sitemap-product-{uuid4().hex[:10]}"
    return ProductRepository(db.session).save(
        Product(id=uuid4(), name=slug, slug=slug, price=9.5, is_active=is_active)
    )


def _seed_category(db):
    slug = f"sitemap-category-{uuid4().hex[:10]}"
    return ProductCategoryRepository(db.session).save(
        ProductCategory(id=uuid4(), name=slug, slug=slug)
    )


def _locs(entries):
    return [entry.loc for entry in entries]


def test_product_count_excludes_inactive_products(db):
    provider = _product_provider(db)
    baseline_count = provider.count()

    _seed_product(db, is_active=True)
    _seed_product(db, is_active=True)
    _seed_product(db, is_active=False)

    assert provider.count() == baseline_count + 2


def test_product_page_lists_active_products_only_with_lastmod(db):
    active = _seed_product(db, is_active=True)
    inactive = _seed_product(db, is_active=False)

    entries = list(_product_provider(db).page(0, ALL_ROWS))

    by_loc = {entry.loc: entry for entry in entries}
    assert f"/shop/product/{inactive.slug}" not in by_loc
    active_entry = by_loc[f"/shop/product/{active.slug}"]
    assert active_entry.lastmod == active.updated_at.isoformat()


def test_product_pages_are_ordered_by_id_and_honour_offset_and_limit(db):
    seeded = [_seed_product(db, is_active=True) for _ in range(4)]
    provider = _product_provider(db)

    full_sequence = _locs(provider.page(0, ALL_ROWS))
    first_half = _locs(provider.page(0, 2))
    rest = _locs(provider.page(2, ALL_ROWS))

    assert first_half + rest == full_sequence
    assert len(first_half) == 2
    seeded_in_id_order = [
        f"/shop/product/{product.slug}"
        for product in sorted(seeded, key=lambda product: str(product.id))
    ]
    assert [loc for loc in full_sequence if loc in seeded_in_id_order] == (
        seeded_in_id_order
    )
    assert full_sequence == _locs(provider.page(0, ALL_ROWS))  # stable


def test_category_provider_counts_and_pages_every_category(db):
    provider = _category_provider(db)
    baseline_count = provider.count()

    category = _seed_category(db)

    assert provider.count() == baseline_count + 1
    entries = {entry.loc: entry for entry in provider.page(0, ALL_ROWS)}
    category_entry = entries[f"/shop/category/{category.slug}"]
    assert category_entry.lastmod == category.updated_at.isoformat()
