import contextlib

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.logging import configure_logging
from app.queue import ArqQueue
from app.routes.health import router as health_router
from app.routes.jobs import router as jobs_router


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
        yield
        await pool.aclose()
        await engine.dispose()

    app = FastAPI(title="APIfy", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(jobs_router)
    return app


app = create_app()
