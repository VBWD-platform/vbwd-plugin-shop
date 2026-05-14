"""Smoke integration test: prove the shop product repository round-trips
through a real PostgreSQL session.

Goes through ProductRepository (no raw SQL — see
feedback_no_direct_db_for_test_data.md) and asserts the row is fetchable
both by id and through the repository's slug/active filters.

Sized to be the cheapest assertion that defends:
  - the SQLAlchemy mapper for Product
  - the shop conftest wiring (test DB, create_all, drop_all)
  - BaseRepository.save() committing rather than just flushing

Sprint: docs/dev_log/20260514/sprints/02-shop-ci-fix.md
"""
from decimal import Decimal

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.repositories.product_repository import ProductRepository


def test_product_save_then_round_trips_through_real_db(db):
    repository = ProductRepository(db.session)

    new_product = Product(
        name="Smoke Widget",
        slug="smoke-widget",
        price=Decimal("9.99"),
        price_float=9.99,
        currency="EUR",
        is_active=True,
    )
    saved_product = repository.save(new_product)

    fetched_by_id = repository.find_by_id(saved_product.id)
    fetched_by_slug = repository.find_by_slug("smoke-widget")
    active_listing = repository.find_active(page=1, per_page=10)

    assert fetched_by_id is not None
    assert fetched_by_id.slug == "smoke-widget"
    assert fetched_by_id.price == Decimal("9.99")

    assert fetched_by_slug is not None
    assert fetched_by_slug.id == saved_product.id

    assert any(product.id == saved_product.id for product in active_listing)
