"""E-commerce plugin demo data — thin wrapper over the shared seed (S88).

The seed logic lives in ``plugins/shop/shop/demo_seed.py`` (``seed_catalog``),
which ``flask reset-demo`` runs through core's demo-data registry. This module
keeps the standalone ``python plugins/shop/populate_db.py`` entrypoint working
by delegating to that single source.
"""
from vbwd.extensions import db


def populate(app=None):
    """Populate shop demo data (idempotent) — delegates to seed_catalog."""
    from plugins.shop.shop.demo_seed import seed_catalog

    seed_catalog(db.session)


if __name__ == "__main__":
    from vbwd.app import create_app

    app = create_app()
    with app.app_context():
        populate(app)
