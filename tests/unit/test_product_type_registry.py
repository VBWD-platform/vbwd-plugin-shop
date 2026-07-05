"""S116.1 — the ProductTypeRegistry seam (register + dedupe, DB-free)."""
import pytest

from plugins.shop.shop.services.product_type_registry import (
    DIGITAL_TYPE_DESCRIPTOR,
    ProductTypeRegistry,
)


def test_register_normalizes_and_defaults_source_to_plugin():
    registry = ProductTypeRegistry()
    registry.register({"slug": "real_estate", "name": "Real estate"})
    descriptors = registry.descriptors()
    assert len(descriptors) == 1
    assert descriptors[0]["slug"] == "real_estate"
    assert descriptors[0]["source"] == "plugin"
    assert descriptors[0]["product_type_fields"] == []


def test_register_is_idempotent_by_slug():
    registry = ProductTypeRegistry()
    registry.register({"slug": "digital", "name": "One"})
    registry.register({"slug": "digital", "name": "Two"})
    descriptors = registry.descriptors()
    assert len(descriptors) == 1
    assert descriptors[0]["name"] == "Two"


def test_descriptors_are_sorted_by_slug():
    registry = ProductTypeRegistry()
    registry.register({"slug": "zeta", "name": "Z"})
    registry.register({"slug": "alpha", "name": "A"})
    assert [d["slug"] for d in registry.descriptors()] == ["alpha", "zeta"]


def test_register_rejects_empty_slug():
    registry = ProductTypeRegistry()
    with pytest.raises(ValueError):
        registry.register({"name": "no slug"})


def test_unregister_and_clear():
    registry = ProductTypeRegistry()
    registry.register({"slug": "digital", "name": "D"})
    registry.unregister("digital")
    assert registry.descriptors() == []
    registry.register({"slug": "cars", "name": "C"})
    registry.clear()
    assert registry.descriptors() == []


def test_digital_descriptor_is_plugin_sourced_with_fields():
    assert DIGITAL_TYPE_DESCRIPTOR["slug"] == "digital"
    assert DIGITAL_TYPE_DESCRIPTOR["source"] == "plugin"
    field_slugs = {f["slug"] for f in DIGITAL_TYPE_DESCRIPTOR["product_type_fields"]}
    assert {"download_url", "license_key"} <= field_slugs
