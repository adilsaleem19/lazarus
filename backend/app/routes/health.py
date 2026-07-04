from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session

router = APIRouter(tags=["health"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: Session) -> dict:
    await session.execute(sa.text("SELECT 1"))
    return {"status": "ready"}
