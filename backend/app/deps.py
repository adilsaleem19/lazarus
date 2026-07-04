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
