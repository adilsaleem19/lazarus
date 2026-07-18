import contextlib

import redis.asyncio as redis
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.logging import configure_logging
from app.queue import ArqQueue
from app.ratelimit import JobRateLimiter
from app.routes.gallery import router as gallery_router
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router
from app.routes.public_api import router as public_api_router


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        engine = make_engine(app_settings.database_url)
        pool = await create_pool(RedisSettings.from_dsn(app_settings.redis_url))
        app.state.settings = app_settings
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.queue = ArqQueue(pool)
        # The arq pool is a full redis client; reuse it for rate limiting.
        app.state.limiter = JobRateLimiter(
            pool,
            per_ip=app_settings.jobs_per_hour_per_ip,
            global_limit=app_settings.jobs_per_hour_global,
        )
        # A plain redis client for SSE pub/sub (decoded strings, own connections).
        events_redis = redis.from_url(app_settings.redis_url, decode_responses=True)
        app.state.events_redis = events_redis
        yield
        await events_redis.aclose()
        await pool.aclose()
        await engine.dispose()

    app = FastAPI(title="Lazarus", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(jobs_router)
    # gallery before public_api so /api/gallery beats the /api/{slug} catch-all.
    app.include_router(gallery_router)
    app.include_router(public_api_router)
    return app


app = create_app()
