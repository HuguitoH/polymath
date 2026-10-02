"""PDF to searchable chunks: parse, chunk, embed, store."""

import asyncio
import hashlib
from enum import StrEnum
from pathlib import Path

from polymath.research.chunker import chunk_paragraphs
from polymath.research.parser import parse_structure
from polymath.research.store import Paper, PaperStore


class IngestError(RuntimeError):
    """Raised when a PDF yields nothing worth storing."""


class Outcome(StrEnum):
    STORED = "stored"
    UNCHANGED = "unchanged"


async def ingest_pdf(pdf: Path, citekey: str, title: str, store: PaperStore) -> Outcome:
    """Ingest one PDF. Re-running on the same file costs one query, not a re-embedding."""
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if await store.is_current(citekey, digest):
        return Outcome.UNCHANGED

    # Parsing is CPU-bound: keep it off the event loop.
    structure = await asyncio.to_thread(parse_structure, pdf)
    chunks = chunk_paragraphs(structure.paragraphs)
    if not chunks:
        raise IngestError(f"{pdf.name}: no chunks (no 'Introduction' heading found?)")

    await store.replace(Paper(citekey, title, digest), chunks, structure.page_labels)
    return Outcome.STORED
