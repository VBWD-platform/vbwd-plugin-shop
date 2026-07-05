"""S116.1 — reconcile idempotency + admin rows survive (integration).

Uses a fresh, test-local registry (never the module singleton) with unique slugs
so the assertions are independent of the persisted ``digital`` row that shop's
``on_enable`` reconciles at app-fixture setup.
"""
from uuid import uuid4

from plugins.shop.shop.models.product_type import (
    PRODUCT_TYPE_SOURCE_ADMIN,
    PRODUCT_TYPE_SOURCE_PLUGIN,
    ProductType,
)
from plugins.shop.shop.repositories.product_type_repository import (
    ProductTypeRepository,
)
from plugins.shop.shop.services.product_type_registry import (
    ProductTypeRegistry,
    reconcile_product_types,
)


def _unique_slug(prefix):
    return f"{prefix}-{uuid4().hex[:8]}"


def test_reconcile_inserts_plugin_type_then_is_idempotent(db):
    slug = _unique_slug("vertical")
    registry = ProductTypeRegistry()
    registry.register(
        {
            "slug": slug,
            "name": "Vertical",
            "product_type_fields": [{"slug": "x", "type": "string", "label": "X"}],
        }
    )

    inserted_first = reconcile_product_types(db.session, registry)
    assert inserted_first == 1

    inserted_second = reconcile_product_types(db.session, registry)
    assert inserted_second == 0

    repo = ProductTypeRepository(db.session)
    row = repo.find_by_slug(slug)
    assert row is not None
    assert row.source == PRODUCT_TYPE_SOURCE_PLUGIN


def test_reconcile_overwrites_plugin_field_cluster(db):
    slug = _unique_slug("vertical")
    registry = ProductTypeRegistry()
    registry.register(
        {
            "slug": slug,
            "name": "First",
            "product_type_fields": [{"slug": "a", "type": "string"}],
        }
    )
    reconcile_product_types(db.session, registry)

    registry.register(
        {
            "slug": slug,
            "name": "Second",
            "product_type_fields": [{"slug": "b", "type": "string"}],
        }
    )
    reconcile_product_types(db.session, registry)

    row = ProductTypeRepository(db.session).find_by_slug(slug)
    assert row.name == "Second"
    assert row.product_type_fields == [{"slug": "b", "type": "string"}]


def test_reconcile_never_clobbers_admin_row(db):
    slug = _unique_slug("adminmade")
    admin_row = ProductType(
        id=uuid4(),
        slug=slug,
        name="Admin type",
        product_type_fields=[{"slug": "keep", "type": "string"}],
        source=PRODUCT_TYPE_SOURCE_ADMIN,
        is_active=True,
    )
    db.session.add(admin_row)
    db.session.commit()

    registry = ProductTypeRegistry()
    registry.register(
        {
            "slug": slug,
            "name": "Plugin tries to steal",
            "product_type_fields": [{"slug": "stolen", "type": "string"}],
        }
    )
    reconcile_product_types(db.session, registry)

    row = ProductTypeRepository(db.session).find_by_slug(slug)
    assert row.source == PRODUCT_TYPE_SOURCE_ADMIN
    assert row.name == "Admin type"
    assert row.product_type_fields == [{"slug": "keep", "type": "string"}]
