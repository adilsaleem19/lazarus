"""Validate extractor output against the LLM-declared record schema.

A schema is {"fields": [{"name", "type", "required"}, ...]}. We build a pydantic
model from it and check every record, plus non-emptiness and per-field coverage.
Field coverage (how often an optional field is actually populated) is reported so
the repair loop and the UI can spot half-working extractions.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "str": str,
    "integer": int,
    "int": int,
    "number": float,
    "float": float,
    "boolean": bool,
    "bool": bool,
}


@dataclass
class ValidationReport:
    ok: bool
    reason: str
    record_count: int
    coverage: dict[str, float] = field(default_factory=dict)


def _py_type(type_name: str) -> Any:
    return _TYPE_MAP.get((type_name or "string").lower(), str)


def build_validator(schema: dict) -> type[BaseModel]:
    fields: dict[str, tuple] = {}
    for spec in schema.get("fields", []):
        name = spec["name"]
        py_type = _py_type(spec.get("type", "string"))
        if spec.get("required", False):
            fields[name] = (py_type, ...)
        else:
            fields[name] = (py_type | None, None)
    return create_model(
        "Record", __config__=ConfigDict(extra="allow", coerce_numbers_to_str=False), **fields
    )


def validate_records(
    records: list[dict], schema: dict, *, min_coverage: float = 0.0
) -> ValidationReport:
    field_specs = schema.get("fields", [])
    if not records:
        return ValidationReport(
            ok=False, reason="extraction returned an empty list", record_count=0
        )

    Model = build_validator(schema)
    from pydantic import ValidationError

    for i, record in enumerate(records):
        try:
            Model(**record)
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", []))
            return ValidationReport(
                ok=False,
                reason=f"record {i} failed validation on field {loc!r}: {first.get('msg')}",
                record_count=len(records),
            )

    coverage: dict[str, float] = {}
    for spec in field_specs:
        name = spec["name"]
        present = sum(1 for r in records if r.get(name) not in (None, ""))
        coverage[name] = present / len(records)

    low = [
        spec["name"]
        for spec in field_specs
        if spec.get("required", False) and coverage.get(spec["name"], 0) < max(min_coverage, 1.0)
    ]
    if low:
        return ValidationReport(
            ok=False,
            reason=f"required field(s) {low} missing from some records",
            record_count=len(records),
            coverage=coverage,
        )

    return ValidationReport(
        ok=True, reason="all records valid", record_count=len(records), coverage=coverage
    )
