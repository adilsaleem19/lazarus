"""The live API fabric: every successful extraction is served at GET /api/{slug}.

Data comes straight from the Postgres cache (stale-while-revalidate: the arq
refresh job updates it in the background; requests never trigger a scrape).
Paused extractors still serve their last good data, clearly marked; evicted
ones return 410 Gone.
"""

from typing import Annotated
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session
from app.models import Extractor, utcnow
from app.openapi_gen import build_spec

router = APIRouter(prefix="/api", tags=["public-api"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def latest_extractor(session: AsyncSession, slug: str) -> Extractor:
    stmt = (
        sa.select(Extractor)
        .where(Extractor.slug == slug)
        .order_by(Extractor.version.desc())
        .limit(1)
    )
    extractor = (await session.execute(stmt)).scalar_one_or_none()
    if extractor is None:
        raise HTTPException(status_code=404, detail=f"no API named {slug!r}")
    if extractor.status == "evicted":
        raise HTTPException(
            status_code=410,
            detail=f"the {slug!r} API was retired: {extractor.paused_reason or 'evicted'}",
        )
    return extractor


@router.get("/{slug}")
async def get_extractor_data(slug: str, session: Session) -> dict:
    extractor = await latest_extractor(session, slug)

    extractor.last_accessed_at = utcnow()
    await session.commit()

    host = urlsplit(extractor.source_url).hostname or extractor.source_url
    data = extractor.data or []
    return {
        "slug": extractor.slug,
        "source_url": extractor.source_url,
        "description": extractor.description or "",
        "status": extractor.status,
        "paused_reason": extractor.paused_reason,
        "record_count": len(data),
        "last_refreshed": extractor.last_refreshed_at,
        "attribution": f"Data extracted from {host} by Lazarus. Source: {extractor.source_url}",
        "data": data,
    }


@router.get("/{slug}/openapi.json")
async def get_extractor_openapi(slug: str, session: Session) -> dict:
    extractor = await latest_extractor(session, slug)
    return build_spec(extractor)


@router.get("/{slug}/docs", include_in_schema=False)
async def get_extractor_docs(slug: str, session: Session) -> HTMLResponse:
    extractor = await latest_extractor(session, slug)
    return get_swagger_ui_html(
        openapi_url=f"/api/{extractor.slug}/openapi.json",
        title=f"Lazarus API: {extractor.slug} — docs",
    )
