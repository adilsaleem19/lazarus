import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_queue, get_session
from app.ingestion.urlguard import UnsafeURLError, validate_target_url
from app.job_states import JobStatus
from app.models import Job, PageSnapshot
from app.queue import JobQueue
from app.schemas import JobCreate, JobOut, SnapshotDetail, SnapshotSummary

router = APIRouter(tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]
Queue = Annotated[JobQueue, Depends(get_queue)]


def _job_out(job: Job, snapshot: PageSnapshot | None) -> JobOut:
    summary = None
    if snapshot is not None:
        summary = SnapshotSummary(
            token_estimate=snapshot.token_estimate,
            xhr_count=len(snapshot.xhr or []),
            structures=snapshot.structures or [],
            robots_status=snapshot.robots_status,
        )
    return JobOut(
        id=str(job.id),
        url=job.url,
        status=job.status,
        reason=job.reason,
        created_at=job.created_at,
        snapshot=summary,
    )


async def _latest_snapshot(session: AsyncSession, job_id: uuid.UUID) -> PageSnapshot | None:
    stmt = (
        sa.select(PageSnapshot)
        .where(PageSnapshot.job_id == job_id)
        .order_by(PageSnapshot.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.post("/jobs", status_code=202, response_model=JobOut)
async def create_job(payload: JobCreate, session: Session, queue: Queue) -> JobOut:
    try:
        # Syntactic checks only here; the worker re-validates with DNS resolution.
        url = validate_target_url(payload.url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = Job(url=url, status=JobStatus.QUEUED.value)
    session.add(job)
    await session.commit()
    await queue.enqueue_analyze(job.id)
    return _job_out(job, None)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: Session) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    snapshot = await _latest_snapshot(session, job.id)
    return _job_out(job, snapshot)


@router.get("/jobs/{job_id}/snapshot", response_model=SnapshotDetail)
async def get_snapshot(job_id: uuid.UUID, session: Session) -> SnapshotDetail:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    snapshot = await _latest_snapshot(session, job.id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no snapshot for this job yet")
    return SnapshotDetail(
        skeleton=snapshot.skeleton,
        token_estimate=snapshot.token_estimate,
        meta=snapshot.meta or {},
        xhr=snapshot.xhr or [],
        structures=snapshot.structures or [],
        robots_status=snapshot.robots_status,
        robots_reason=snapshot.robots_reason,
    )
