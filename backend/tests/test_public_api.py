"""Tests for the public data endpoints: GET /api/{slug} and its OpenAPI docs."""

from datetime import UTC, datetime

from app.models import Extractor

RECORDS = [{"title": "Alpha", "url": "/a"}, {"title": "Beta", "url": "/b"}]
SCHEMA = {
    "fields": [
        {"name": "title", "type": "string", "required": True},
        {"name": "url", "type": "string", "required": False},
    ]
}


async def make_extractor(sessionmaker, **overrides) -> Extractor:
    values = dict(
        slug="site-test",
        source_url="https://site.test/page",
        strategy="html",
        code="def extract(html):\n    return []",
        record_schema=SCHEMA,
        version=1,
        sample=RECORDS,
        data=RECORDS,
        description="Items extracted from site.test.",
        status="active",
        last_refreshed_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    )
    values.update(overrides)
    async with sessionmaker() as session:
        ext = Extractor(**values)
        session.add(ext)
        await session.commit()
        return ext


async def test_serves_cached_data_with_envelope(api, sessionmaker):
    await make_extractor(sessionmaker)
    resp = await api.get("/api/site-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == RECORDS
    assert body["record_count"] == 2
    assert body["source_url"] == "https://site.test/page"
    assert body["last_refreshed"].startswith("2026-07-18T12:00")
    assert "site.test" in body["attribution"]
    assert body["status"] == "active"


async def test_unknown_slug_404(api):
    resp = await api.get("/api/never-heard-of-it")
    assert resp.status_code == 404


async def test_serves_latest_version(api, sessionmaker):
    await make_extractor(sessionmaker, version=1, data=[{"title": "old"}])
    await make_extractor(sessionmaker, version=2, data=[{"title": "new"}])
    resp = await api.get("/api/site-test")
    assert resp.json()["data"] == [{"title": "new"}]


async def test_paused_extractor_still_serves_stale_data(api, sessionmaker):
    await make_extractor(
        sessionmaker, status="paused", paused_reason="3 consecutive refresh failures"
    )
    resp = await api.get("/api/site-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "paused"
    assert "refresh failures" in body["paused_reason"]
    assert body["data"] == RECORDS


async def test_evicted_extractor_is_gone(api, sessionmaker):
    await make_extractor(sessionmaker, status="evicted", paused_reason="LRU eviction")
    resp = await api.get("/api/site-test")
    assert resp.status_code == 410


async def test_access_updates_last_accessed(api, sessionmaker):
    ext = await make_extractor(sessionmaker)
    assert ext.last_accessed_at is None
    await api.get("/api/site-test")
    async with sessionmaker() as session:
        refreshed = await session.get(Extractor, ext.id)
        assert refreshed.last_accessed_at is not None


class TestOpenAPI:
    async def test_spec_reflects_record_schema(self, api, sessionmaker):
        await make_extractor(sessionmaker)
        resp = await api.get("/api/site-test/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        assert spec["openapi"].startswith("3.1")
        assert "site-test" in spec["info"]["title"]
        assert spec["info"]["description"] == "Items extracted from site.test."

        record = spec["components"]["schemas"]["Record"]
        assert record["properties"]["title"]["type"] == "string"
        assert "title" in record["required"]
        assert "url" not in record.get("required", [])

        path = spec["paths"]["/api/site-test"]["get"]
        assert path["responses"]["200"]
        # a real record from the live sample is embedded as the example
        assert record["example"] == RECORDS[0]

    async def test_spec_404_for_unknown_slug(self, api):
        resp = await api.get("/api/nope/openapi.json")
        assert resp.status_code == 404

    async def test_docs_serve_swagger_ui(self, api, sessionmaker):
        await make_extractor(sessionmaker)
        resp = await api.get("/api/site-test/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()
        assert "/api/site-test/openapi.json" in resp.text
