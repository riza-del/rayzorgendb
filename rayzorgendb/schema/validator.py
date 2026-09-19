"""
RayzorgenDB Schema System

Optional schema validation for collections.
Enforce field types, required fields, defaults.

Usage:
    from rayzorgendb.schema import Schema, Field

    schema = Schema({
        "nama": Field(str, required=True),
        "umur": Field(int, min=0, max=150),
        "email": Field(str, pattern=r".+@.+"),
    })

    users = db.collection("users", schema=schema)
"""

import re
from typing import Any, Callable, Dict, List, Optional, Type


class SchemaError(Exception):
    """Raised when data fails validation."""
    pass


class Field:
    """A single field definition."""

    def __init__(self, type_: Type = None,
                 required: bool = False,
                 default: Any = None,
                 min: float = None,
                 max: float = None,
                 min_length: int = None,
                 max_length: int = None,
                 pattern: str = None,
                 choices: List[Any] = None,
                 validator: Callable = None):
        self.type = type_
        self.required = required
        self.default = default
        self.min = min
        self.max = max
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.choices = choices
        self.validator = validator

    def validate(self, value: Any, field_name: str) -> Any:
        """Validate value, return cleaned value."""
        # None handling
        if value is None:
            if self.required:
                raise SchemaError(
                    "Field '" + field_name + "' is required"
                )
            if self.default is not None:
                return self.default
            return None

        # Type check
        if self.type is not None:
            if not isinstance(value, self.type):
                # Try coercion
                try:
                    if self.type is int and isinstance(value, str):
                        value = int(value)
                    elif self.type is float and isinstance(value, (int, str)):
                        value = float(value)
                    elif self.type is str:
                        value = str(value)
                    elif self.type is bool:
                        if isinstance(value, str):
                            value = value.lower() in ("true", "1", "yes")
                        else:
                            value = bool(value)
                    else:
                        raise SchemaError(
                            "Field '" + field_name + "' expected "
                            + self.type.__name__ + ", got "
                            + type(value).__name__
                        )
                except (ValueError, TypeError):
                    raise SchemaError(
                        "Field '" + field_name + "' expected "
                        + self.type.__name__ + ", got "
                        + type(value).__name__
                    )

        # Range check
        if self.min is not None:
            if isinstance(value, (int, float)) and value < self.min:
                raise SchemaError(
                    "Field '" + field_name + "' must be >= "
                    + str(self.min)
                )
        if self.max is not None:
            if isinstance(value, (int, float)) and value > self.max:
                raise SchemaError(
                    "Field '" + field_name + "' must be <= "
                    + str(self.max)
                )

        # Length check
        if isinstance(value, (str, list, dict)):
            if self.min_length is not None and len(value) < self.min_length:
                raise SchemaError(
                    "Field '" + field_name + "' too short"
                )
            if self.max_length is not None and len(value) > self.max_length:
                raise SchemaError(
                    "Field '" + field_name + "' too long"
                )

        # Pattern check
        if self.pattern is not None and isinstance(value, str):
            if not re.match(self.pattern, value):
                raise SchemaError(
                    "Field '" + field_name + "' does not match pattern"
                )

        # Choices
        if self.choices is not None:
            if value not in self.choices:
                raise SchemaError(
                    "Field '" + field_name + "' must be one of "
                    + str(self.choices)
                )

        # Custom validator
        if self.validator is not None:
            if not self.validator(value):
                raise SchemaError(
                    "Field '" + field_name + "' failed custom validation"
                )

        return value


class Schema:
    """Schema for a collection."""

    def __init__(self, fields: Dict[str, Field],
                 strict: bool = False):
        """
        Args:
            fields: dict of field_name -> Field
            strict: if True, reject extra fields not in schema
        """
        self.fields = fields
        self.strict = strict

    def validate(self, data: Dict) -> Dict:
        """Validate and clean data."""
        cleaned = {}
        errors = []

        # Validate defined fields
        for name, field in self.fields.items():
            value = data.get(name)
            try:
                cleaned[name] = field.validate(value, name)
            except SchemaError as e:
                errors.append(str(e))

        # Handle extra fields
        if self.strict:
            for name in data:
                if name not in self.fields:
                    errors.append(
                        "Unknown field: '" + name + "'"
                    )
        else:
            for name, value in data.items():
                if name not in self.fields:
                    cleaned[name] = value

        if errors:
            raise SchemaError("; ".join(errors))

        return cleaned

    def to_dict(self) -> Dict:
        """Serialize schema to dict."""
        return {
            "fields": list(self.fields.keys()),
            "strict": self.strict,
        }


__all__ = ["Schema", "Field", "SchemaError"]
