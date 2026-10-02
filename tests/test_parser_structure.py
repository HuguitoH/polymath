"""Parser regression tests: one expected file per publisher sample.

Expected files describe what a reader sees in the PDF. Most samples are paywalled,
so the PDFs live in tests/fixtures/private/ (gitignored) and their tests skip when absent.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from polymath.research.parser import PaperStructure, parse_structure

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = sorted((FIXTURES / "parser" / "expected").glob("*.yaml"))
PRIVATE = FIXTURES / "private"

# "2.1. ", "4.1 ", "IV. " at the start of a title
NUMBERING = re.compile(r"^(\d+(\.\d+)*\.?|[IVX]+\.)\s+")

Case = tuple[dict[str, Any], PaperStructure]


def normalise(title: str) -> str:
    """Compare titles as a reader would: ignore numbering, case and spacing. Never symbols."""
    return " ".join(NUMBERING.sub("", title.strip()).split()).casefold()


@pytest.fixture(scope="module", params=EXPECTED, ids=lambda path: path.stem)
def case(request: pytest.FixtureRequest) -> Case:
    """Parse each sample PDF once, shared by the three tests below."""
    expected: dict[str, Any] = yaml.safe_load(request.param.read_text(encoding="utf-8"))
    pdf = PRIVATE / expected["file"]
    if not pdf.exists():
        pytest.skip(f"{pdf.name} is not in tests/fixtures/private/")
    return expected, parse_structure(pdf)


def test_headings_match_the_printed_structure(case: Case) -> None:
    expected, actual = case
    want = [(h["level"], h["page"], normalise(h["title"])) for h in expected["headings"]]
    got = [(h.level, h.page, normalise(h.title)) for h in actual.headings]
    assert got == want  # order matters: it defines the section path


def test_statements_are_found_and_proofs_linked(case: Case) -> None:
    expected, actual = case
    want = [(s["page"], s["label"], s.get("proves")) for s in expected["statements"]]
    got = [(s.page, s.label, s.proves) for s in actual.statements]
    assert got == want


def test_every_caption_is_found_on_its_page(case: Case) -> None:
    expected, actual = case
    want = sorted((c["page"], c["label"]) for c in expected["captions"])
    got = sorted((c.page, c.label) for c in actual.captions)
    assert got == want  # sorted: within a page, extraction order is not reading order
