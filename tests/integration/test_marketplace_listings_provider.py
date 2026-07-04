"""Shop marketplace vendor-listings provider (integration).

The shop vertical contributes a ``vendor_listings_provider`` the marketplace
registry calls to aggregate a user's product listings. This test exercises the
provider DIRECTLY against a real session — it never imports the marketplace
plugin, so it passes in the per-plugin isolated CI (which clones shop alone).

Seeds through ``ProductRepository`` (no raw SQL) and asserts:
  - an empty list for a vendor who owns nothing (Liskov: safe empty result),
  - the vendor's own ``Product.to_dict()`` for a vendor who owns one product,
  - another vendor's product is excluded (ownership scoping).
"""
from uuid import uuid4

from vbwd.models.user import User

from plugins.shop.shop.marketplace_listings import vendor_listings_provider
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.repositories.product_repository import ProductRepository


def _make_vendor(db):
    """Seed a real core user (vendor_id has a FK to users) and return its id."""
    user = User(email=f"shop-vendor-{uuid4().hex}@example.com", password_hash="x")
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_product(db, vendor_id, name):
    repository = ProductRepository(db.session)
    product = Product(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        price=12.5,
        is_active=True,
        vendor_id=vendor_id,
    )
    return repository.save(product)


def test_provider_returns_empty_for_vendor_without_products(db):
    unknown_vendor_id = uuid4()

    assert vendor_listings_provider(unknown_vendor_id) == []


def test_provider_returns_only_the_vendors_own_product_dicts(db):
    vendor_id = _make_vendor(db)
    other_vendor_id = _make_vendor(db)

    owned = _make_product(db, vendor_id, "Owned Widget")
    _make_product(db, other_vendor_id, "Other Widget")

    listings = vendor_listings_provider(vendor_id)

    assert len(listings) == 1
    assert listings[0] == owned.to_dict()
    assert listings[0]["id"] == str(owned.id)
