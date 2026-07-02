"""Product carries a nullable ``vendor_id`` and serialises it.

Ownership: a vendor-owned product records the owning user's id; a
platform-owned product leaves it ``None``. ``to_dict`` exposes it so the admin
UI / marketplace can read the owner.
"""
from uuid import uuid4


def test_product_to_dict_includes_vendor_id():
    from plugins.shop.shop.models.product import Product

    vendor_id = uuid4()
    product = Product(
        id=uuid4(),
        name="Vendor Widget",
        slug=f"vw-{uuid4().hex[:8]}",
        price=10.0,
        vendor_id=vendor_id,
    )
    serialized = product.to_dict()
    assert "vendor_id" in serialized
    assert serialized["vendor_id"] == str(vendor_id)


def test_product_to_dict_vendor_id_none_for_platform_product():
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(),
        name="Platform Widget",
        slug=f"pw-{uuid4().hex[:8]}",
        price=10.0,
    )
    assert product.to_dict()["vendor_id"] is None
