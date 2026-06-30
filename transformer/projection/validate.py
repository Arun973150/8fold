"""Build a JSON Schema from a runtime config and validate a projected view.

Every output -- default or custom -- is validated before it is returned. For the
default schema we validate against the canonical schema in model.py. For a custom
config we derive a schema from each field's declared ``type`` + ``required`` so the
contract the caller asked for is actually enforced.
"""

from __future__ import annotations

from typing import Optional

import jsonschema

from ..model import DEFAULT_SCHEMA

# Map config type strings to JSON Schema fragments.
_TYPE_MAP = {
    "string": {"type": "string"},
    "string[]": {"type": "array", "items": {"type": "string"}},
    "number": {"type": "number"},
    "integer": {"type": "integer"},
    "boolean": {"type": "boolean"},
    "object": {"type": "object"},
}


def schema_for_config(config: Optional[dict]) -> dict:
    if config is None:
        return DEFAULT_SCHEMA

    properties = {}
    required = []
    for field in config.get("fields", []):
        key = field["path"]
        base = dict(_TYPE_MAP.get(field.get("type", "string"), {"type": "string"}))
        is_required = bool(field.get("required"))
        if is_required:
            required.append(key)
        else:
            # Non-required fields may be null (on_missing='null').
            t = base.get("type")
            if isinstance(t, str):
                base["type"] = [t, "null"]
        properties[key] = base

    if config.get("include_confidence"):
        properties["overall_confidence"] = {"type": "number"}
    if config.get("include_provenance"):
        properties["provenance"] = {"type": "array"}

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def validate(view: dict, config: Optional[dict]) -> None:
    """Raise jsonschema.ValidationError if ``view`` violates its schema."""
    jsonschema.validate(instance=view, schema=schema_for_config(config))
