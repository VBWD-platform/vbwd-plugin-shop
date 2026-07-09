"""Admin bulk-copy (duplicate) product API (integration).

Contract for ``POST /api/v1/admin/shop/products/bulk-copy`` (shop's bulk
convention: ``{"product_ids": [...]}``):

- a copy is ALWAYS created inactive (never live);
- ``name`` gets the `` " (Copy)"`` suffix;
- ``slug`` (UNIQUE) is uniquified — ``-copy``, then ``-copy-2`` … — and is
  collision-safe when the same product is copied twice AND when two products are
  bulk-copied in one call;
- ``sku`` (UNIQUE, nullable) keeps ``None`` when the source has none, else is
  derived + uniquified the same way;
- owned children (variants, images) are DUPLICATED with new ids re-pointed at the
  new product; variant ``sku`` is uniquified too;
- shared refs (taxes M2M, categories M2M, the ``product_type`` row) are
  RE-POINTED, never duplicated;
- ``type_field_values`` are preserved;
- an unknown id is skipped (not fatal);
- ``shop.products.manage`` is required.
"""
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.models.enums import UserRole, UserStatus
from vbwd.models.user import User
from vbwd.models.tax import Tax


@pytest.fixture
def client(app):
    return app.test_client()


HEADERS = {"Authorization": "Bearer valid"}


def _make_admin(db):
    admin = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:8]}@example.com",
        password_hash="x",
        status=UserStatus.ACTIVE,
        role=UserRole.ADMIN,
    )
    db.session.add(admin)
    db.session.commit()
    return admin


def _auth_as_admin(monkeypatch, admin, *, has_permission=True):
    import vbwd.middleware.auth as auth_mod

    repo = MagicMock()
    repo.find_by_id.return_value = admin
    svc = MagicMock()
    svc.verify_token.return_value = str(admin.id)
    monkeypatch.setattr(auth_mod, "UserRepository", lambda *a, **k: repo)
    monkeypatch.setattr(auth_mod, "AuthService", lambda *a, **k: svc)
    monkeypatch.setattr(type(admin), "is_admin", property(lambda self: True))
    monkeypatch.setattr(
        type(admin), "has_permission", lambda self, perm: has_permission
    )


def _make_product(
    db,
    *,
    name="Widget",
    slug=None,
    sku=None,
    is_active=True,
    has_variants=False,
    product_type_slug=None,
    type_field_values=None,
    with_tax=False,
    with_category=False,
):
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name=name,
        slug=slug or f"widget-{uuid4().hex[:8]}",
        sku=sku,
        description="A widget.",
        price=9.99,
        is_active=is_active,
        has_variants=has_variants,
        sort_order=5,
        weight=Decimal("1.250"),
        dimensions={"w": 10, "h": 20},
        product_metadata={"origin": "DE"},
        tax_class="reduced",
        price_display_mode="netto",
        product_type_slug=product_type_slug,
        type_field_values=type_field_values or {},
    )
    if with_tax:
        tax = Tax(
            id=uuid4(),
            name="Reduced",
            code=f"RED_{uuid4().hex[:6]}",
            rate=Decimal("7.00"),
            is_active=True,
        )
        db.session.add(tax)
        product.taxes = [tax]
    db.session.add(product)
    db.session.commit()
    if with_category:
        from plugins.shop.shop.models.product_category import ProductCategory

        category = ProductCategory(
            id=uuid4(),
            name="Tools",
            slug=f"tools-{uuid4().hex[:8]}",
        )
        db.session.add(category)
        category.products.append(product)
        db.session.commit()
    return product


def _add_variant(db, product, *, name, sku, price="4.99"):
    from plugins.shop.shop.models.product_variant import ProductVariant

    variant = ProductVariant(
        id=uuid4(),
        product_id=product.id,
        name=name,
        sku=sku,
        price=Decimal(price),
        price_float=float(price),
        weight=Decimal("0.500"),
        is_active=True,
        sort_order=0,
        attributes={"size": "M"},
        image_url="https://cdn.example/v.png",
    )
    db.session.add(variant)
    db.session.commit()
    return variant


def _add_image(db, product, *, url, is_primary=False, sort_order=0):
    from plugins.shop.shop.models.product_image import ProductImage

    image = ProductImage(
        id=uuid4(),
        product_id=product.id,
        url=url,
        alt="alt text",
        sort_order=sort_order,
        is_primary=is_primary,
    )
    db.session.add(image)
    db.session.commit()
    return image


def _copy(client, product_ids):
    return client.post(
        "/api/v1/admin/shop/products/bulk-copy",
        json={"product_ids": [str(pid) for pid in product_ids]},
        headers=HEADERS,
    )


def test_copy_is_inactive_and_renamed(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, name="Hammer", sku="SKU-1")

    resp = _copy(client, [product.id])
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["count"] == 1
    copy = body["products"][0]
    assert copy["id"] != str(product.id)
    assert copy["is_active"] is False
    assert copy["name"] == "Hammer (Copy)"
    # Base scalar fields are carried over.
    assert copy["description"] == "A widget."
    assert copy["price"] == 9.99
    assert copy["tax_class"] == "reduced"
    assert copy["price_display_mode"] == "netto"
    assert copy["dimensions"] == {"w": 10, "h": 20}


def test_slug_and_sku_uniquified_when_copying_same_product_twice(
    db, client, monkeypatch
):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, slug="drill", sku="DRILL")

    first = _copy(client, [product.id]).get_json()["products"][0]
    second = _copy(client, [product.id]).get_json()["products"][0]

    assert first["slug"] == "drill-copy"
    assert second["slug"] == "drill-copy-2"
    assert first["sku"] == "DRILL-copy"
    assert second["sku"] == "DRILL-copy-2"


def test_bulk_copy_two_products_in_one_call(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    first_product = _make_product(db, slug="saw", sku="SAW")
    second_product = _make_product(db, slug="chisel", sku="CHISEL")

    resp = _copy(client, [first_product.id, second_product.id])
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["count"] == 2
    slugs = {p["slug"] for p in resp.get_json()["products"]}
    skus = {p["sku"] for p in resp.get_json()["products"]}
    assert slugs == {"saw-copy", "chisel-copy"}
    assert skus == {"SAW-copy", "CHISEL-copy"}


def test_same_product_copied_twice_in_one_call_is_collision_safe(
    db, client, monkeypatch
):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, slug="saw", sku="SAW")

    # The reserved-set guard must keep the two copies distinct even within a
    # single call (both derive from the same source slug/sku).
    resp = _copy(client, [product.id, product.id])
    assert resp.status_code == 201, resp.get_json()
    slugs = {p["slug"] for p in resp.get_json()["products"]}
    skus = {p["sku"] for p in resp.get_json()["products"]}
    assert slugs == {"saw-copy", "saw-copy-2"}
    assert skus == {"SAW-copy", "SAW-copy-2"}


def test_null_sku_stays_null(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, sku=None)

    copy = _copy(client, [product.id]).get_json()["products"][0]
    assert copy["sku"] is None


def test_variants_duplicated_and_repointed(db, client, monkeypatch):
    from plugins.shop.shop.repositories.product_variant_repository import (
        ProductVariantRepository,
    )

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, has_variants=True)
    _add_variant(db, product, name="Small", sku="V-S")
    _add_variant(db, product, name="Large", sku="V-L")

    copy = _copy(client, [product.id]).get_json()["products"][0]
    copy_id = copy["id"]

    repo = ProductVariantRepository(db.session)
    new_variants = repo.list_for_product(copy_id)
    assert len(new_variants) == 2
    for variant in new_variants:
        assert str(variant.product_id) == copy_id
    new_skus = {variant.sku for variant in new_variants}
    assert new_skus == {"V-S-copy", "V-L-copy"}
    # Source variants are untouched.
    assert len(repo.list_for_product(product.id)) == 2


def test_variant_null_sku_stays_null(db, client, monkeypatch):
    from plugins.shop.shop.repositories.product_variant_repository import (
        ProductVariantRepository,
    )

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, has_variants=True)
    _add_variant(db, product, name="OneSize", sku=None)

    copy = _copy(client, [product.id]).get_json()["products"][0]
    new_variants = ProductVariantRepository(db.session).list_for_product(copy["id"])
    assert len(new_variants) == 1
    assert new_variants[0].sku is None


def test_images_duplicated(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)
    _add_image(db, product, url="https://cdn/a.png", is_primary=True, sort_order=0)
    _add_image(db, product, url="https://cdn/b.png", sort_order=1)

    copy = _copy(client, [product.id]).get_json()["products"][0]
    assert len(copy["images"]) == 2
    urls = {image["url"] for image in copy["images"]}
    assert urls == {"https://cdn/a.png", "https://cdn/b.png"}
    # New image rows (different ids) pointing at the same media strings.
    source_image_ids = {str(image.id) for image in product.images}
    copy_image_ids = {image["id"] for image in copy["images"]}
    assert source_image_ids.isdisjoint(copy_image_ids)


def test_taxes_and_categories_repointed_not_duplicated(db, client, monkeypatch):
    from plugins.shop.shop.models.product_category import ProductCategory

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db, with_tax=True, with_category=True)
    source_tax_ids = {tax["id"] for tax in product.to_dict()["taxes"]}
    source_category_ids = {str(c.id) for c in product.categories}

    tax_count_before = db.session.query(Tax).count()
    category_count_before = db.session.query(ProductCategory).count()

    copy = _copy(client, [product.id]).get_json()["products"][0]

    # Same referenced rows, not new ones.
    assert {tax["id"] for tax in copy["taxes"]} == source_tax_ids
    assert {c["id"] for c in copy["categories"]} == source_category_ids
    assert db.session.query(Tax).count() == tax_count_before
    assert db.session.query(ProductCategory).count() == category_count_before


def test_typed_product_copy_preserves_type_without_duplicating_type_row(
    db, client, monkeypatch
):
    from plugins.shop.shop.models.product_type import (
        PRODUCT_TYPE_SOURCE_ADMIN,
        ProductType,
    )
    from plugins.shop.shop.repositories.product_type_repository import (
        ProductTypeRepository,
    )

    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    type_slug = f"typed-{uuid4().hex[:8]}"
    db.session.add(
        ProductType(
            id=uuid4(),
            slug=type_slug,
            name="Class type",
            product_type_fields=[
                {"slug": "strength", "type": "string", "label": "Strength"},
            ],
            source=PRODUCT_TYPE_SOURCE_ADMIN,
            is_active=True,
        )
    )
    db.session.commit()
    product = _make_product(
        db,
        product_type_slug=type_slug,
        type_field_values={"strength": "500mg"},
    )

    type_count_before = ProductTypeRepository(db.session).count()
    copy = _copy(client, [product.id]).get_json()["products"][0]

    assert copy["product_type_slug"] == type_slug
    assert copy["type_field_values"] == {"strength": "500mg"}
    assert ProductTypeRepository(db.session).count() == type_count_before


def test_unknown_id_is_skipped(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin)
    product = _make_product(db)

    resp = _copy(client, [product.id, uuid4()])
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["count"] == 1
    assert len(body["products"]) == 1


def test_permission_required(db, client, monkeypatch):
    admin = _make_admin(db)
    _auth_as_admin(monkeypatch, admin, has_permission=False)
    product = _make_product(db)

    resp = _copy(client, [product.id])
    assert resp.status_code == 403
