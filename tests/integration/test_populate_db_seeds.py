"""Integration: populate_db seeds the shop product catalog on install.

Proves the standalone entrypoint (`python plugins/shop/populate_db.py`) now
actually seeds: `populate()` runs under an app context (the `db` fixture
provides one — the same context the `__main__` block creates via create_app),
writes the demo products + categories, and is idempotent on a second run.

`populate()` also runs the optional CMS + checkout + email seeding paths; the
autouse fixture below registers those models so `create_all()` builds their
tables (each path guards its own import and is itself idempotent).
"""
import pytest

from plugins.shop.populate_db import populate
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.product_category import ProductCategory


@pytest.fixture(autouse=True)
def _register_optional_plugin_models(db):
    # populate() also seeds CMS layouts/pages, the checkout-confirmation page,
    # and email templates when those optional plugins are installed. Register
    # their models so create_all() builds the tables; tolerate their absence in
    # isolated plugin CI (each populate path guards its own import).
    try:
        import plugins.cms.src.models  # noqa: F401
    except ImportError:
        pass
    try:
        import plugins.email.src.models.email_template  # noqa: F401
    except ImportError:
        pass

    db.create_all()


def test_populate_seeds_products_and_categories(db):
    populate()

    assert db.session.query(Product).count() > 0
    assert db.session.query(ProductCategory).count() > 0
    assert (
        db.session.query(Product).filter_by(slug="wireless-headphones-pro").first()
        is not None
    )


def test_populate_is_idempotent(db):
    populate()
    first_count = db.session.query(Product).count()

    populate()
    assert db.session.query(Product).count() == first_count


def test_seed_catalog_session_taking_and_idempotent(db):
    """S88: the shared ``seed_catalog(session)`` upserts through the passed
    session and is idempotent (the reset-demo registry contract)."""
    from plugins.shop.shop.demo_seed import seed_catalog

    stats = seed_catalog(db.session)
    assert stats["shop_products"] > 0
    first_count = db.session.query(Product).count()

    seed_catalog(db.session)
    assert db.session.query(Product).count() == first_count
