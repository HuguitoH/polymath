"""HTTP surface.

Reads are database reads: a GET never triggers generation. Only /reply
costs an embedding.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from polymath.api_errors import install as install_error_handlers
from polymath.config import Settings
from polymath.kernel.db import make_pool
from polymath.kernel.embedding import OllamaEmbedder
from polymath.kernel.events import Event, Modality, Source
from polymath.kernel.store import EventStore
from polymath.observability.logs import configure as configure_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Container:
    """Everything the handlers need, resolved once at startup.

    Explicit and typed: a handler declares its dependency in its signature
    instead of reaching into module-level state.
    """

    settings: Settings
    pool: AsyncConnectionPool
    store: EventStore


def get_container(request: Request) -> Container:
    """FastAPI dependency. app.state is framework-owned, not our globals."""
    container: Container = request.app.state.container
    return container


Deps = Annotated[Container, Depends(get_container)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(service_name="polymath-api")
    pool = make_pool(settings)
    await pool.open()
    async with httpx.AsyncClient() as client:
        app.state.container = Container(
            settings=settings,
            pool=pool,
            store=EventStore(pool, OllamaEmbedder(settings, client)),
        )
        logger.info("api ready")
        yield
    await pool.close()


app = FastAPI(title="Polymath", lifespan=lifespan)
install_error_handlers(app)


# --- schemas ---------------------------------------------------------------


class ReplyRequest(BaseModel):
    """Something Hugo said. Higher salience than news: it decays far slower."""

    text: str = Field(min_length=1, max_length=4000)
    salience: float = Field(default=0.7, ge=0.0, le=1.0)


class ReplyCreated(BaseModel):
    id: UUID


class BriefResponse(BaseModel):
    id: UUID
    occurred_at: datetime
    content: str


class HealthResponse(BaseModel):
    database: str


# --- queries ---------------------------------------------------------------


async def _fetch_latest_brief(pool: AsyncConnectionPool) -> BriefResponse:
    """Shared by two routes, so it lives here rather than one calling the other."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT id, occurred_at, content
            FROM event
            WHERE metadata->>'kind' = 'morning_brief'
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="no brief has been composed yet")

    return BriefResponse(id=row[0], occurred_at=row[1], content=row[2])


# --- routes ----------------------------------------------------------------


@app.get("/health")
async def health(deps: Deps) -> HealthResponse:
    """Readiness, not liveness: can we do the job right now?"""
    try:
        async with deps.pool.connection() as conn:
            await conn.execute("SELECT 1")
        return HealthResponse(database="ok")
    except Exception:
        logger.warning("database health check failed", exc_info=True)
        return HealthResponse(database="down")


@app.get("/brief/latest")
async def latest_brief(deps: Deps) -> BriefResponse:
    return await _fetch_latest_brief(deps.pool)


@app.get("/brief/latest/audio")
async def latest_brief_audio(deps: Deps) -> RedirectResponse:
    """Stable URL, redirecting to an immutable one so the client can cache it."""
    brief = await _fetch_latest_brief(deps.pool)
    return RedirectResponse(url=f"/media/{brief.id}.wav")


@app.get("/media/{event_id}.wav")
async def media(event_id: UUID, deps: Deps) -> FileResponse:
    """Audio never changes for a given event, so it caches forever."""
    path = deps.settings.audio_dir / f"{event_id}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no audio for this event")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.post("/reply", status_code=201)
async def reply(payload: ReplyRequest, deps: Deps) -> ReplyCreated:
    """Hugo's own words enter the store. This is what makes recall real."""
    event = Event(
        source=Source.CHAT,
        modality=Modality.TEXT,
        content=payload.text,
        salience=payload.salience,
        occurred_at=datetime.now(UTC),
        metadata={"via": "api"},
    )
    stored = await deps.store.append(event)
    logger.info("stored reply %s", stored.id)
    return ReplyCreated(id=stored.id)
