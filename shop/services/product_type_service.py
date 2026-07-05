"""Product-type save-time validation (S116.1).

A product referencing a type must carry ``type_field_values`` that satisfy that
type's ``product_type_fields``: required fields present, each value's Python type
matches the declared field ``type``, and ``select`` / ``multiselect`` values are
drawn from the field's ``options``. A product with **no** type must carry no
values.

Pure, DB-free helpers so the route layer maps a :class:`ProductTypeValidationError`
to a 400 and the rules stay unit-testable in isolation.
"""
from typing import Iterable, List, Mapping, Optional

# Declared field ``type`` values whose stored value must be a plain string.
_STRING_FIELD_TYPES = ("string", "text", "url", "textarea")
# Field types resolved against the field's ``options`` list.
_SELECT_FIELD_TYPE = "select"
_MULTISELECT_FIELD_TYPE = "multiselect"
_NUMBER_FIELD_TYPES = ("number", "float", "decimal")
_INTEGER_FIELD_TYPE = "integer"
_BOOLEAN_FIELD_TYPE = "boolean"


class ProductTypeValidationError(Exception):
    """Raised when a product's ``type_field_values`` violate its type's schema.

    The shop routes map this to a 400 (bad request).
    """


def _is_empty(value: object) -> bool:
    """A required value is "missing" when absent, ``None`` or an empty string/list."""
    return value is None or value == "" or value == []


def _validate_single_value(
    field_slug: str, field_type: str, value: object, options: Optional[Iterable]
) -> None:
    """Validate one present (non-empty) value against its declared ``field_type``.

    Unknown field types are accepted as-is (forward-compatible); only the known
    vocabulary is type-checked. Raises :class:`ProductTypeValidationError`.
    """
    option_values = list(options or [])
    if field_type in _STRING_FIELD_TYPES:
        if not isinstance(value, str):
            raise ProductTypeValidationError(
                f"Field '{field_slug}' expects a string value"
            )
    elif field_type == _BOOLEAN_FIELD_TYPE:
        if not isinstance(value, bool):
            raise ProductTypeValidationError(
                f"Field '{field_slug}' expects a boolean value"
            )
    elif field_type == _INTEGER_FIELD_TYPE:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProductTypeValidationError(
                f"Field '{field_slug}' expects an integer value"
            )
    elif field_type in _NUMBER_FIELD_TYPES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProductTypeValidationError(
                f"Field '{field_slug}' expects a numeric value"
            )
    elif field_type == _SELECT_FIELD_TYPE:
        if value not in option_values:
            raise ProductTypeValidationError(
                f"Field '{field_slug}' value {value!r} is not one of its options"
            )
    elif field_type == _MULTISELECT_FIELD_TYPE:
        if not isinstance(value, list):
            raise ProductTypeValidationError(
                f"Field '{field_slug}' expects a list of values"
            )
        for item in value:
            if item not in option_values:
                raise ProductTypeValidationError(
                    f"Field '{field_slug}' value {item!r} is not one of its options"
                )


def validate_type_field_values(
    product_type_fields: List[Mapping],
    values: Optional[Mapping],
) -> dict:
    """Validate ``values`` against a type's ``product_type_fields``.

    Returns the values dict (unchanged — orphaned keys from a previous type are
    retained, non-destructive per S116 §G) on success, or raises
    :class:`ProductTypeValidationError` on the first violation.
    """
    supplied = dict(values or {})
    for field in product_type_fields or []:
        field_slug = field.get("slug")
        if not field_slug:
            continue
        field_type = field.get("type", "string")
        is_required = bool(field.get("required", False))
        has_value = field_slug in supplied and not _is_empty(supplied[field_slug])

        if is_required and not has_value:
            raise ProductTypeValidationError(f"Field '{field_slug}' is required")
        if has_value:
            _validate_single_value(
                field_slug, field_type, supplied[field_slug], field.get("options")
            )
    return supplied
