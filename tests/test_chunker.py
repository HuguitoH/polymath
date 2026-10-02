"""Chunking regression tests over the same six publisher samples as the parser."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from polymath.research.chunker import MAX_WORDS, SKIP_SECTIONS, Chunk, chunk_paragraphs
from polymath.research.parser import bare_title, parse_structure

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = sorted((FIXTURES / "parser" / "expected").glob("*.yaml"))
PRIVATE = FIXTURES / "private"

Case = tuple[dict[str, Any], list[Chunk]]


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture(scope="module", params=EXPECTED, ids=lambda path: path.stem)
def case(request: pytest.FixtureRequest) -> Case:
    expected: dict[str, Any] = yaml.safe_load(request.param.read_text(encoding="utf-8"))
    pdf = PRIVATE / expected["file"]
    if not pdf.exists():
        pytest.skip(f"{pdf.name} is not in tests/fixtures/private/")
    return expected, chunk_paragraphs(parse_structure(pdf).paragraphs)


def test_each_passage_lands_whole_in_one_chunk_of_its_section(case: Case) -> None:
    expected, chunks = case
    for passage in expected["passages"]:
        holders = [c for c in chunks if flat(passage["text"]) in flat(c.text)]
        assert len(holders) == 1, f"{passage['text'][:40]!r} found in {len(holders)} chunks"
        chunk = holders[0]
        assert [bare_title(t) for t in chunk.section] == [bare_title(t) for t in passage["section"]]
        assert chunk.page_start <= passage["page"] <= chunk.page_end


def test_no_chunk_exceeds_the_size_limit(case: Case) -> None:
    _, chunks = case
    assert chunks, "no chunks at all"
    assert max(c.words for c in chunks) <= MAX_WORDS


def test_skipped_sections_and_running_headers_stay_out(case: Case) -> None:
    expected, chunks = case
    assert not [c for c in chunks if bare_title(c.section[0]) in SKIP_SECTIONS]
    for unwanted in expected["never_in_chunks"]:
        assert not [c for c in chunks if unwanted in c.text], f"{unwanted!r} leaked into a chunk"


def test_chunks_are_prose_not_equations(case: Case) -> None:
    _, chunks = case
    for chunk in chunks:
        words = re.findall(r"\b[a-z]{3,}\b", chunk.text)
        assert len(words) >= 5, chunk.text[:80]
