from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.queue import JobQueue


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_queue(request: Request) -> JobQueue:
    return request.app.state.queue


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_limiter(request: Request):
    return request.app.state.limiter


def client_ip(request: Request) -> str:
    # Caddy terminates TLS and sets X-Forwarded-For; first hop is the client.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
