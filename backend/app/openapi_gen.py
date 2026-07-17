"""Per-extractor OpenAPI 3.1 spec, generated from the agent's record schema.

The spec is cheap to build, so it is rendered on demand from the stored schema,
the LLM-written description, and a real record from the live sample as example.
"""

_TYPE_MAP = {
    "string": "string",
    "str": "string",
    "integer": "integer",
    "int": "integer",
    "number": "number",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
}


def _field_schema(spec: dict) -> dict:
    openapi_type = _TYPE_MAP.get((spec.get("type") or "string").lower(), "string")
    if spec.get("required", False):
        return {"type": openapi_type}
    return {"type": [openapi_type, "null"]}


def build_spec(extractor) -> dict:
    fields = (extractor.record_schema or {}).get("fields", [])
    properties = {f["name"]: _field_schema(f) for f in fields}
    required = [f["name"] for f in fields if f.get("required", False)]

    record: dict = {"type": "object", "properties": properties}
    if required:
        record["required"] = required
    if extractor.sample:
        record["example"] = extractor.sample[0]

    description = (
        extractor.description
        or f"Data automatically extracted from {extractor.source_url} by Lazarus."
    )
    path = f"/api/{extractor.slug}"
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"Lazarus API: {extractor.slug}",
            "version": str(extractor.version),
            "description": description,
        },
        "externalDocs": {
            "description": "Original source page",
            "url": extractor.source_url,
        },
        "paths": {
            path: {
                "get": {
                    "summary": f"Latest data extracted from {extractor.source_url}",
                    "description": description,
                    "operationId": f"get_{extractor.slug.replace('-', '_')}",
                    "responses": {
                        "200": {
                            "description": "Cached records plus refresh metadata",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/Envelope"
                                    }
                                }
                            },
                        },
                        "404": {"description": "Unknown API slug"},
                        "410": {"description": "This API was retired"},
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Record": record,
                "Envelope": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "source_url": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "string"},
                        "paused_reason": {"type": ["string", "null"]},
                        "record_count": {"type": "integer"},
                        "last_refreshed": {"type": ["string", "null"], "format": "date-time"},
                        "attribution": {"type": "string"},
                        "data": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Record"},
                        },
                    },
                },
            }
        },
    }
