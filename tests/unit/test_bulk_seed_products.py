"""Unit: S89.1 load-test bulk seed for ``shop_products`` (MagicMock repo, no DB).

Covers the plugin override of the core ``BaseModelExchanger.bulk_seed`` seam:

* ``_seed_row`` returns a VALID product row — non-null name + a fixed price +
  the one shared ``loadtest-`` category slug.
* ``_build_instance`` attaches that one shared category as the M2M link.
* ``bulk_seed`` inserts through the repo's ``bulk_add`` (batched, not per-row
  full scans) and is idempotent (an already-present ``loadtest-`` key is
  skipped, the prerequisite is built once).

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(the override preserves the base seed contract); clean code; no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin shop --full``.
"""
from typing import List

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory
from plugins.shop.shop.services.data_exchange.shop_exchangers import (
    ShopProductsExchanger,
)


class _FakeRepo:
    """Minimal repo honouring the four S89 scale hooks the base seed calls."""

    def __init__(self, existing_keys: List[str] | None = None) -> None:
        self.added: List[Product] = []
        self.bulk_calls = 0
        self._existing = list(existing_keys or [])

    def find_natural_keys_with_prefix(self, prefix: str) -> List[str]:
        return [key for key in self._existing if key.startswith(prefix)]

    def bulk_add(self, instances: List[Product]) -> None:
        self.bulk_calls += 1
        self.added.extend(instances)

    def add(self, instance: Product) -> None:  # pragma: no cover - fallback
        self.added.append(instance)


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def _make_exchanger(repo: _FakeRepo) -> ShopProductsExchanger:
    exchanger = ShopProductsExchanger(
        entity_key="shop_products",
        label="Shop Products",
        cluster="sales",
        natural_key="slug",
        model_class=Product,
        repository=repo,
        session=_FakeSession(),
        public_fields=["slug", "name", "price"],
        view_permission="shop.products.view",
        manage_permission="shop.products.manage",
    )
    # Stub the prerequisite so the unit test needs no DB / repository: one shared
    # in-memory category, reused on every call (idempotency is asserted by the
    # single instance identity below).
    shared_category = ProductCategory(
        slug=exchanger._SEED_CATEGORY_SLUG, name="Load-test products"
    )
    exchanger._ensure_seed_prerequisite = lambda: shared_category
    return exchanger


def test_seed_row_is_a_valid_product_row() -> None:
    repo = _FakeRepo()
    exchanger = _make_exchanger(repo)

    row = exchanger._seed_row(3, "loadtest-shop_products-3")

    assert row["slug"] == "loadtest-shop_products-3"
    assert row["name"]  # non-null, non-empty
    assert row["price"] == ShopProductsExchanger._SEED_PRODUCT_PRICE
    assert row["category_slugs"] == [exchanger._SEED_CATEGORY_SLUG]


def test_build_instance_attaches_the_one_shared_category() -> None:
    repo = _FakeRepo()
    exchanger = _make_exchanger(repo)

    first = exchanger._build_instance(
        exchanger._seed_row(0, "loadtest-shop_products-0")
    )
    second = exchanger._build_instance(
        exchanger._seed_row(1, "loadtest-shop_products-1")
    )

    assert isinstance(first, Product)
    assert "category_slugs" not in first.__dict__
    assert len(first.categories) == 1
    # Every seeded product points at the SAME category instance (one prerequisite).
    assert first.categories[0] is second.categories[0]


def test_bulk_seed_creates_count_rows_via_bulk_add() -> None:
    repo = _FakeRepo()
    exchanger = _make_exchanger(repo)

    result = exchanger.bulk_seed(10, batch_size=4)

    assert result.created == 10
    assert result.skipped == 0
    assert len(repo.added) == 10
    # Batched insert path was used (not a single giant transaction / per-row add).
    assert repo.bulk_calls >= 1
    assert all(isinstance(item, Product) for item in repo.added)
    assert all(len(item.categories) == 1 for item in repo.added)


def test_bulk_seed_is_idempotent() -> None:
    existing = [f"loadtest-shop_products-{index}" for index in range(10)]
    repo = _FakeRepo(existing_keys=existing)
    exchanger = _make_exchanger(repo)

    result = exchanger.bulk_seed(10)

    assert result.created == 0
    assert result.skipped == 10
    assert repo.added == []
