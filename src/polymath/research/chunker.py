"""Chunks: the unit retrieval returns and the model reads.

A chunk never crosses a section, so it holds one idea and can be cited by section and page.
Which sections are worth indexing is decided here, not in the parser.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby

from polymath.research.parser import Paragraph, bare_title

MAX_WORDS = 300  # ~400 bge-m3 tokens: one idea, still a precise embedding. Tuned by the eval.

# Top-level sections with nothing to retrieve. Nomenclature and appendices stay:
# "what does beta mean in Lu?" is a fair question.
SKIP_SECTIONS = frozenset(
    {
        "references",
        "acknowledgments",
        "acknowledgements",
        "acknowledgement",
        "funding",
        "declaration of conflicting interests",
        "disclosure statement",
        "notes on contributors",
        "orcid",
        "orcid id",
    }
)

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


@dataclass(frozen=True)
class Chunk:
    section: tuple[str, ...]
    page_start: int
    page_end: int
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


def chunk_paragraphs(
    paragraphs: Iterable[Paragraph],
    max_words: int = MAX_WORDS,
    skip: frozenset[str] = SKIP_SECTIONS,
) -> list[Chunk]:
    """Pack consecutive paragraphs of one section into chunks of at most max_words.

    No overlap: chunks end on paragraph or sentence boundaries, so no sentence is cut.
    """
    chunks: list[Chunk] = []
    for section, grouped in groupby(paragraphs, key=lambda p: p.section):
        if section and bare_title(section[0]) in skip:
            continue
        chunks.extend(_pack(section, _pieces(grouped, max_words), max_words))
    return chunks


def _pieces(paragraphs: Iterable[Paragraph], max_words: int) -> Iterator[Paragraph]:
    """Paragraphs as they are, or split at sentence ends when one alone is too long."""
    for paragraph in paragraphs:
        if len(paragraph.text.split()) <= max_words:
            yield paragraph
            continue
        for sentence in SENTENCE_END.split(paragraph.text):
            yield Paragraph(paragraph.page_start, paragraph.page_end, paragraph.section, sentence)


def _pack(section: tuple[str, ...], pieces: Iterable[Paragraph], max_words: int) -> Iterator[Chunk]:
    current: list[Paragraph] = []
    for piece in pieces:
        size = sum(len(p.text.split()) for p in current) + len(piece.text.split())
        if current and size > max_words:
            yield _chunk(section, current)
            current = []
        current.append(piece)
    if current:
        yield _chunk(section, current)


def _chunk(section: tuple[str, ...], pieces: list[Paragraph]) -> Chunk:
    return Chunk(
        section=section,
        page_start=pieces[0].page_start,
        page_end=pieces[-1].page_end,
        text=" ".join(p.text for p in pieces),
    )
