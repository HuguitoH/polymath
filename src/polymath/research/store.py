"""Persistence for papers and their chunks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from polymath.kernel.embedding import Embedder
from polymath.research.chunker import Chunk


@dataclass(frozen=True, slots=True)
class Paper:
    citekey: str
    title: str
    pdf_sha256: str


class PaperStore:
    """Papers are upserted by citekey; their chunks are replaced as a whole.

    Unlike events, chunks are derived data: when the PDF changes, the old chunks
    describe a document that no longer exists, so they are deleted, not kept.
    """

    def __init__(self, pool: AsyncConnectionPool, embedder: Embedder) -> None:
        self._pool = pool
        self._embedder = embedder

    async def is_current(self, citekey: str, pdf_sha256: str) -> bool:
        """True if this exact PDF was already ingested with the current embedding model."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT 1 FROM paper p
                WHERE p.citekey = %s AND p.pdf_sha256 = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM chunk c
                      WHERE c.paper_id = p.id AND c.embedding_model <> %s
                  )
                """,
                (citekey, pdf_sha256, self._embedder.model_name),
            )
            return await cur.fetchone() is not None

    async def replace(
        self, paper: Paper, chunks: Sequence[Chunk], page_labels: Sequence[str | None]
    ) -> None:
        """Store the paper and exactly these chunks, atomically.

        Embeddings are computed first: a slow or failing embedder must not hold a
        transaction open, and must not leave a paper half replaced.
        """
        vectors = [await self._embedder.embed(_embedding_text(paper, c)) for c in chunks]

        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                """
                INSERT INTO paper (id, citekey, title, pdf_sha256)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (citekey) DO UPDATE
                    SET title = EXCLUDED.title,
                        pdf_sha256 = EXCLUDED.pdf_sha256,
                        ingested_at = now()
                RETURNING id
                """,
                (uuid.uuid4(), paper.citekey, paper.title, paper.pdf_sha256),
            )
            row = await cur.fetchone()
            if row is None:  # RETURNING always yields the upserted row; say so if it ever does not
                raise RuntimeError(f"upsert of paper {paper.citekey!r} returned no row")
            paper_id = row[0]

            await conn.execute("DELETE FROM chunk WHERE paper_id = %s", (paper_id,))
            async with conn.cursor() as insert:
                await insert.executemany(
                    """
                    INSERT INTO chunk (
                        id, paper_id, ordinal, section, page_start, page_end,
                        page_label, content, embedding, embedding_model
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            uuid.uuid4(),
                            paper_id,
                            ordinal,
                            list(chunk.section),
                            chunk.page_start,
                            chunk.page_end,
                            _label(page_labels, chunk.page_start),
                            chunk.text,
                            vector,
                            self._embedder.model_name,
                        )
                        for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                    ],
                )


def _embedding_text(paper: Paper, chunk: Chunk) -> str:
    """What gets embedded: the chunk, prefixed with where it comes from.

    "It reduced the RMSE by 40%" alone does not say which paper or which part of it;
    with the title and section path in front, the vector does. Only the chunk itself
    is stored as content.
    """
    return f"{paper.title}\n{' > '.join(chunk.section)}\n\n{chunk.text}"


def _label(page_labels: Sequence[str | None], page: int) -> str | None:
    return page_labels[page - 1] if 0 < page <= len(page_labels) else None
