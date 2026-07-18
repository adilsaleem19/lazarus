"""GET /gallery — the public list of live APIs backing the frontend gallery grid.

Only active extractors, newest first. Since a slug can have multiple versions
(older ones marked 'superseded'), 'active' already isolates the current one.
"""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session
from app.models import Extractor

# Under /api (not a bare /gallery) so it can't collide with the frontend's own
# /gallery page route when both sit behind the same Caddy origin.
router = APIRouter(prefix="/api", tags=["gallery"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/gallery")
async def list_apis(session: Session) -> dict:
    stmt = (
        sa.select(Extractor)
        .where(Extractor.status == "active")
        .order_by(Extractor.created_at.desc())
    )
    extractors = (await session.execute(stmt)).scalars().all()
    return {
        "apis": [
            {
                "slug": e.slug,
                "endpoint": f"/api/{e.slug}",
                "docs": f"/api/{e.slug}/docs",
                "source_url": e.source_url,
                "description": e.description or "",
                "strategy": e.strategy,
                "version": e.version,
                "record_count": len(e.data or []),
                "last_refreshed": e.last_refreshed_at,
                "created_at": e.created_at,
            }
            for e in extractors
        ]
    }
