"""Test fixtures.

Tests run inside a transaction that is always rolled back, so they can never
commit to the database they connect to. Nothing is truncated.
"""

import hashlib
import random

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from pgvector.psycopg import register_vector_async

from polymath.config import Settings
from polymath.kernel.store import EventStore

class FakeEmbedder:
    """Deterministic embedder. Keeps store tests off the GPU and the network.

    Each text gets its own direction, seeded from a hash of the text. Cosine
    distance ignores length, so a constant vector per text would make every
    vector parallel: all distances 0, and any search would "find" anything.
    """

    model_name = "fake"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        rng = random.Random(hashlib.sha256(text.encode()).digest())
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dimensions)]

class _SingleConnectionPool:
    """Hands every caller the same open connection.

    EventStore expects a pool; giving it one connection inside an open
    transaction is what lets the test roll everything back afterwards.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    def connection(self) -> "_NoClose":
        return _NoClose(self._connection)


class _NoClose:
    """Async context manager that yields the connection without closing it."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> AsyncConnection:
        return self._connection

    async def __aexit__(self, *exc_info: object) -> None:
        return None


@pytest_asyncio.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    """One connection, one transaction, always rolled back."""
    conn = await AsyncConnection.connect(Settings().database_url, autocommit=False)
    await register_vector_async(conn)
    try:
        yield conn
    finally:
        await conn.rollback()
        await conn.close()


@pytest_asyncio.fixture
async def store(connection: AsyncConnection) -> EventStore:
    return EventStore(_SingleConnectionPool(connection), FakeEmbedder())  # type: ignore[arg-type]
