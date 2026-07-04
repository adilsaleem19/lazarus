"""Tests for the jobs HTTP API: submission, retrieval, validation, health."""

import uuid

from app.job_states import JobStatus
from app.models import Job, PageSnapshot


async def test_healthz(api):
    resp = await api.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


class TestCreateJob:
    async def test_valid_url_is_accepted_and_enqueued(self, api, app):
        resp = await api.post("/jobs", json={"url": "https://example.com/news"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["url"] == "https://example.com/news"
        assert app.state.queue.enqueued == [body["id"]]

    async def test_non_http_scheme_is_rejected(self, api, app):
        resp = await api.post("/jobs", json={"url": "file:///etc/passwd"})
        assert resp.status_code == 422
        assert app.state.queue.enqueued == []

    async def test_private_address_is_rejected(self, api, app):
        resp = await api.post("/jobs", json={"url": "http://169.254.169.254/latest"})
        assert resp.status_code == 422
        assert app.state.queue.enqueued == []
        assert resp.json()["detail"]


class TestGetJob:
    async def test_unknown_job_is_404(self, api):
        resp = await api.get(f"/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_queued_job_has_no_snapshot(self, api):
        created = (await api.post("/jobs", json={"url": "https://example.com/a"})).json()
        resp = await api.get(f"/jobs/{created['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["snapshot"] is None

    async def test_done_job_exposes_snapshot_summary(self, api, sessionmaker):
        async with sessionmaker() as session:
            job = Job(url="https://example.com/b", status=JobStatus.DONE.value)
            session.add(job)
            await session.flush()
            session.add(
                PageSnapshot(
                    job_id=job.id,
                    final_html="<html></html>",
                    skeleton="<body></body>",
                    token_estimate=42,
                    meta={"title": "T"},
                    xhr=[{"url": "https://example.com/api", "status": 200}],
                    structures=[{"type": "table", "columns": ["a"], "row_count": 3}],
                    robots_status="allowed",
                )
            )
            await session.commit()
            job_id = str(job.id)

        resp = await api.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        snap = resp.json()["snapshot"]
        assert snap["token_estimate"] == 42
        assert snap["xhr_count"] == 1
        assert snap["structures"][0]["type"] == "table"
        assert snap["robots_status"] == "allowed"

    async def test_snapshot_detail_endpoint_returns_skeleton_and_xhr(self, api, sessionmaker):
        async with sessionmaker() as session:
            job = Job(url="https://example.com/c", status=JobStatus.DONE.value)
            session.add(job)
            await session.flush()
            session.add(
                PageSnapshot(
                    job_id=job.id,
                    final_html="<html>full</html>",
                    skeleton="<body>skel</body>",
                    token_estimate=10,
                    meta={},
                    xhr=[{"url": "https://example.com/api", "status": 200, "body": "{}"}],
                    structures=[],
                    robots_status="allowed",
                )
            )
            await session.commit()
            job_id = str(job.id)

        resp = await api.get(f"/jobs/{job_id}/snapshot")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skeleton"] == "<body>skel</body>"
        assert body["xhr"][0]["url"] == "https://example.com/api"
