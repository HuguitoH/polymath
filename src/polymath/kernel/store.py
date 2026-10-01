from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from polymath.kernel.embedding import Embedder
from polymath.kernel.events import Event, Source


@dataclass(frozen=True, slots=True)
class Candidate:
    """An event retrieved from the store, with its raw vector distance.

    Distance is cosine distance in [0, 2]; similarity is 1 - distance.
    Scoring policy lives in retrieval, not here.
    """

    event: Event
    distance: float


class EventStore:
    """Append-only persistence for events. No update, no delete, by design."""

    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder) -> None:
        self._pool = pool
        self._embedder = embedder

    async def append(self, event: Event) -> Event:
        vector = await self._embedder.embed(event.content)

        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO event (
                    id, occurred_at, source, modality, content, raw_uri,
                    embedding, embedding_model, salience, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.id,
                    event.occurred_at,
                    event.source,
                    event.modality,
                    event.content,
                    event.raw_uri,
                    vector,
                    self._embedder.model_name,
                    event.salience,
                    Jsonb(event.metadata),
                ),
            )
        return event

    async def search_similar(
        self,
        query: str,
        *,
        limit: int = 20,
        sources: frozenset[Source] | None = None,
        since: datetime | None = None,
    ) -> list[Candidate]:
        """Nearest neighbours by cosine distance, optionally filtered."""
        vector = await self._embedder.embed(query)

        sql = ["SELECT *, embedding <=> %s::vector AS distance FROM event"]
        params: list[object] = [vector]
        filters: list[str] = []

        if sources:
            filters.append("source = ANY(%s)")
            params.append([s.value for s in sources])
        if since:
            filters.append("occurred_at >= %s")
            params.append(since)

        if filters:
            sql.append("WHERE " + " AND ".join(filters))
        sql.append("ORDER BY distance LIMIT %s")
        params.append(limit)

        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(" ".join(sql), params)
            rows = await cur.fetchall()

        return [self._to_candidate(row) for row in rows]

    async def recent(
        self, *, since: timedelta, sources: frozenset[Source] | None = None
    ) -> list[Event]:
        """Chronological window - no vector involved."""
        cutoff = datetime.now(UTC) - since

        sql = ["SELECT * FROM event WHERE occurred_at >= %s"]
        params: list[object] = [cutoff]

        if sources:
            sql.append("AND source = ANY(%s)")
            params.append([s.value for s in sources])

        sql.append("ORDER BY occurred_at DESC")

        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(" ".join(sql), params)
            rows = await cur.fetchall()

        return [self._to_candidate(row | {"distance": 0.0}).event for row in rows]

    @staticmethod
    def _to_candidate(row: dict[str, object]) -> Candidate:
        distance = float(row.pop("distance"))  # type: ignore[arg-type]
        row.pop("embedding", None)
        row.pop("embedding_model", None)
        row.pop("embedding_version", None)
        row.pop("ingested_at", None)
        return Candidate(event=Event.model_validate(row), distance=distance)
