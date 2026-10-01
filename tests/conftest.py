"""Test fixtures.

Tests run inside a transaction that is always rolled back, so they can never
commit to the database they connect to. Nothing is truncated.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from pgvector.psycopg import register_vector_async

from polymath.config import Settings
from polymath.kernel.store import EventStore


class FakeEmbedder:
    """Deterministic embedder. Keeps store tests off the GPU and the network."""

    model_name = "fake"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        seed = float(sum(ord(char) for char in text) % 97) / 97.0
        return [seed] * self.dimensions


class _SingleConnectionPool:
    """Hands every caller the same open connection.

    EventStore expects a pool; giving it one connection inside an open
    transaction is what lets the test roll everything back afterwards.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    def connection(self) -> AsyncConnection:
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
