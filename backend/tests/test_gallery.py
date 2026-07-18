"""Tests for GET /gallery — the public list of live APIs."""

from datetime import UTC, datetime, timedelta

from app.models import Extractor


async def add(sessionmaker, slug, **overrides):
    values = dict(
        slug=slug,
        source_url=f"https://{slug}.test/page",
        strategy="html",
        code="def extract(html):\n    return []",
        record_schema={"fields": []},
        version=1,
        data=[{"a": 1}, {"a": 2}],
        description=f"Data from {slug}.",
        status="active",
        last_refreshed_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
    )
    values.update(overrides)
    async with sessionmaker() as session:
        session.add(Extractor(**values))
        await session.commit()


async def test_lists_active_extractors_newest_first(api, sessionmaker):
    await add(sessionmaker, "older", created_at=datetime(2026, 7, 18, 9, 0, tzinfo=UTC))
    await add(sessionmaker, "newer", created_at=datetime(2026, 7, 18, 11, 0, tzinfo=UTC))
    resp = await api.get("/api/gallery")
    assert resp.status_code == 200
    body = resp.json()
    slugs = [e["slug"] for e in body["apis"]]
    assert slugs == ["newer", "older"]
    first = body["apis"][0]
    assert first["record_count"] == 2
    assert first["source_url"] == "https://newer.test/page"
    assert first["description"] == "Data from newer."
    assert first["endpoint"] == "/api/newer"


async def test_excludes_paused_evicted_and_superseded(api, sessionmaker):
    await add(sessionmaker, "live-one")
    await add(sessionmaker, "paused-one", status="paused")
    await add(sessionmaker, "gone", status="evicted")
    await add(sessionmaker, "old-version", status="superseded")
    resp = await api.get("/api/gallery")
    slugs = {e["slug"] for e in resp.json()["apis"]}
    assert slugs == {"live-one"}


async def test_shows_only_latest_version_per_slug(api, sessionmaker):
    await add(sessionmaker, "dup", version=1, status="superseded")
    await add(sessionmaker, "dup", version=2, status="active", data=[{"a": 1}])
    resp = await api.get("/api/gallery")
    apis = resp.json()["apis"]
    assert len(apis) == 1
    assert apis[0]["version"] == 2


async def test_empty_gallery_is_valid(api):
    resp = await api.get("/api/gallery")
    assert resp.status_code == 200
    assert resp.json()["apis"] == []


async def test_gallery_not_shadowed_by_slug_route(api, sessionmaker):
    # /api/gallery must hit the gallery listing, never the /api/{slug} data route.
    await add(sessionmaker, "some-slug")
    resp = await api.get("/api/gallery")
    assert "apis" in resp.json()  # the listing shape, not a data envelope


async def test_reports_relative_freshness(api, sessionmaker):
    recent = datetime.now(UTC) - timedelta(minutes=3)
    await add(sessionmaker, "fresh", last_refreshed_at=recent)
    resp = await api.get("/api/gallery")
    assert resp.json()["apis"][0]["last_refreshed"] is not None
