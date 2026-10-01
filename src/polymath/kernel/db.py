from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from polymath.config import Settings


async def _configure(conn: AsyncConnection) -> None:
    await register_vector_async(conn)


def make_pool(settings: Settings) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        settings.database_url,
        configure=_configure,
        open=False,
        min_size=1,
        max_size=10,
    )
