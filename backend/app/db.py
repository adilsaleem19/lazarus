from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # in-memory test DB must share one connection across sessions
        kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    return create_async_engine(url, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
