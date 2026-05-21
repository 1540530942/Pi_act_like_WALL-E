from __future__ import annotations

from typing import Any


def validate_object_schema(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    """Minimal runtime schema validator (dependency-free).

    Supported fields:
    - type: only "object"
    - required: list[str]
    - properties: {key: {type: "number"|"string"|"boolean", minimum?, maximum?, enum?}}
    """
    if schema.get("type") != "object":
        raise ValueError("schema type must be object")

    required = schema.get("required", [])
    for key in required:
        if key not in payload:
            raise ValueError(f"missing required param: {key}")

    properties = schema.get("properties", {})
    for key, value in payload.items():
        if key not in properties:
            continue
        spec = properties[key]
        typ = spec.get("type")

        if typ == "number":
            if not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be number")
            if "minimum" in spec and value < spec["minimum"]:
                raise ValueError(f"{key} must be >= {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                raise ValueError(f"{key} must be <= {spec['maximum']}")
        elif typ == "string":
            if not isinstance(value, str):
                raise ValueError(f"{key} must be string")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"{key} must be one of {spec['enum']}")
        elif typ == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean")
        elif typ == "array":
            if not isinstance(value, list):
                raise ValueError(f"{key} must be array")
