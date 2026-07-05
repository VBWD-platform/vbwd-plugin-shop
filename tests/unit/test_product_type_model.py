"""S116.1 — ProductType model + Product type-field columns serialise correctly."""
from uuid import uuid4


def test_product_type_to_dict_exposes_field_cluster():
    from plugins.shop.shop.models.product_type import ProductType

    fields = [
        {
            "slug": "download_url",
            "type": "url",
            "label": "Download URL",
            "required": True,
            "options": [],
            "help": None,
            "sort_order": 0,
        },
    ]
    product_type = ProductType(
        id=uuid4(),
        slug="digital",
        name="Digital product",
        description="downloadable",
        product_type_fields=fields,
        source="plugin",
        is_active=True,
    )
    serialized = product_type.to_dict()
    assert serialized["slug"] == "digital"
    assert serialized["name"] == "Digital product"
    assert serialized["description"] == "downloadable"
    assert serialized["product_type_fields"] == fields
    assert serialized["source"] == "plugin"
    assert serialized["is_active"] is True


def test_product_type_to_dict_defaults_fields_to_empty_list():
    from plugins.shop.shop.models.product_type import ProductType

    product_type = ProductType(id=uuid4(), slug="cars", name="Cars")
    assert product_type.to_dict()["product_type_fields"] == []


def test_product_to_dict_includes_type_slug_and_values():
    from plugins.shop.shop.models.product import Product

    values = {"download_url": "https://example.com/x.zip"}
    product = Product(
        id=uuid4(),
        name="Ebook",
        slug=f"ebook-{uuid4().hex[:8]}",
        price=10.0,
        product_type_slug="digital",
        type_field_values=values,
    )
    serialized = product.to_dict()
    assert serialized["product_type_slug"] == "digital"
    assert serialized["type_field_values"] == values


def test_product_to_dict_type_fields_default_for_base_product():
    from plugins.shop.shop.models.product import Product

    product = Product(
        id=uuid4(), name="Plain", slug=f"plain-{uuid4().hex[:8]}", price=1.0
    )
    serialized = product.to_dict()
    assert serialized["product_type_slug"] is None
    assert serialized["type_field_values"] == {}
