"""Shared fixtures: in-memory async DB and an app wired with fakes."""

import httpx
import pytest
from httpx import ASGITransport

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.main import create_app
from app.models import Base


class FakeQueue:
    def __init__(self):
        self.enqueued: list[str] = []

    async def enqueue_analyze(self, job_id) -> None:
        self.enqueued.append(str(job_id))


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="sqlite+aiosqlite://", redis_url="redis://unused:6379/0")


@pytest.fixture
async def engine(settings):
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessionmaker(engine):
    return make_sessionmaker(engine)


@pytest.fixture
async def app(settings, sessionmaker):
    app = create_app(settings)
    app.state.settings = settings
    app.state.sessionmaker = sessionmaker
    app.state.queue = FakeQueue()
    return app


@pytest.fixture
async def api(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
