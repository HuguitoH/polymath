"""PDF structure: headings, formal statements and captions.

The parser reports what the document is. What is worth indexing is decided by the indexer.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf


@dataclass(frozen=True)
class Heading:
    level: int
    page: int  # PDF page, 1-based
    title: str  # as printed, numbering included


@dataclass(frozen=True)
class Statement:
    page: int
    label: str  # "Theorem 1", "Proof"
    proves: str | None = None  # for a Proof: the statement it proves


@dataclass(frozen=True)
class Caption:
    page: int
    label: str  # "Figure 7", "Fig. 7", "Table 1"


@dataclass(frozen=True)
class PaperStructure:
    headings: tuple[Heading, ...] = ()
    statements: tuple[Statement, ...] = ()
    captions: tuple[Caption, ...] = ()


@dataclass(frozen=True)
class Line:
    page: int
    text: str


# A caption opens with its label, a full stop or colon, and its text ("Figure 3. Path model"),
# or the label stands alone on its line (Elsevier: "Table 1" above the caption text).
# Not captions: "Figure 8(c) shows..." (a reference), "Figure 4." alone (a sentence wrapped
# onto a new line), "Figure 12. Cont." (a figure continued from the previous page).
CAPTION = re.compile(
    r"^(?P<label>(?:Fig\.|Figure|Table|TABLE)\s*(?:\d+|[IVX]+))(?:[.:]\s*(?P<rest>\S.*)|\s*$)"
)
CONTINUATION = re.compile(r"^Cont(inued)?\.?$", re.IGNORECASE)


def parse_structure(pdf: Path) -> PaperStructure:
    lines = _read_lines(pdf)
    return PaperStructure(captions=tuple(_captions(lines)))


def _read_lines(pdf: Path) -> list[Line]:
    """Every text line, whatever its font: IEEE sets captions in the body font.

    The only function that touches PyMuPDF, whose type hints are partial;
    everything after this boundary is strictly typed.
    """
    lines: list[Line] = []
    with pymupdf.open(pdf) as doc:  # type: ignore[no-untyped-call]
        for index in range(doc.page_count):
            layout: dict[str, Any] = doc.load_page(index).get_text("dict")
            for block in layout["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if text:
                        lines.append(Line(index + 1, text))
    return lines


def _captions(lines: list[Line]) -> Iterator[Caption]:
    seen: set[str] = set()
    for line in lines:
        match = CAPTION.match(line.text)
        if not match or CONTINUATION.match(match["rest"] or ""):
            continue
        label = " ".join(match["label"].split())
        # The first occurrence is the caption; later ones are cross-references.
        if label not in seen:
            seen.add(label)
            yield Caption(line.page, label)
