"""S116.1 — save-time validation of type_field_values against a field cluster."""
import pytest

from plugins.shop.shop.services.product_type_service import (
    ProductTypeValidationError,
    validate_type_field_values,
)

_FIELDS = [
    {
        "slug": "product_class",
        "type": "select",
        "label": "Class",
        "required": True,
        "options": ["RX", "OTC"],
    },
    {
        "slug": "substances",
        "type": "multiselect",
        "label": "Substances",
        "options": ["a", "b"],
    },
    {"slug": "strength", "type": "string", "label": "Strength"},
    {"slug": "count", "type": "integer", "label": "Count"},
    {"slug": "leaflet", "type": "url", "label": "Leaflet"},
]


def test_happy_path_valid_values_returned():
    values = {
        "product_class": "RX",
        "substances": ["a", "b"],
        "strength": "500mg",
        "count": 12,
        "leaflet": "https://example.com/l.pdf",
    }
    assert validate_type_field_values(_FIELDS, values) == values


def test_missing_required_field_raises():
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(_FIELDS, {"strength": "500mg"})


def test_select_value_not_in_options_raises():
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(_FIELDS, {"product_class": "MEDICAL_DEVICE"})


def test_multiselect_value_not_in_options_raises():
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(
            _FIELDS, {"product_class": "RX", "substances": ["a", "zzz"]}
        )


def test_wrong_type_for_string_raises():
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(_FIELDS, {"product_class": "RX", "strength": 123})


def test_wrong_type_for_integer_raises():
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(_FIELDS, {"product_class": "RX", "count": "twelve"})


def test_boolean_not_accepted_as_integer():
    fields = [{"slug": "n", "type": "integer", "label": "N"}]
    with pytest.raises(ProductTypeValidationError):
        validate_type_field_values(fields, {"n": True})


def test_empty_field_set_accepts_any_values():
    assert validate_type_field_values([], {}) == {}


def test_optional_field_absent_is_ok():
    values = {"product_class": "OTC"}
    assert validate_type_field_values(_FIELDS, values) == values


def test_orphaned_keys_are_retained():
    values = {"product_class": "RX", "legacy_field": "kept"}
    result = validate_type_field_values(_FIELDS, values)
    assert result["legacy_field"] == "kept"
