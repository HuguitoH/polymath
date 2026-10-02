"""PDF structure: headings, formal statements and captions.

The parser reports what the document is. What is worth indexing is decided by the indexer.
"""

import re
from collections import Counter
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
class Span:
    text: str
    font: str
    size: float
    superscript: bool


@dataclass(frozen=True)
class Line:
    page: int
    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        """The line as read, without superscripts (citations such as "Lemma 1.²⁴", footnotes)."""
        return "".join(s.text for s in self.spans if not s.superscript).strip()

    @property
    def font(self) -> str:
        return self.spans[0].font


# A caption opens with its label, a full stop or colon, and its text ("Figure 3. Path model"),
# or the label stands alone on its line (Elsevier: "Table 1" above the caption text).
# Not captions: "Figure 8(c) shows..." (a reference), "Figure 4." alone (a sentence wrapped
# onto a new line), "Figure 12. Cont." (a figure continued from the previous page).
CAPTION = re.compile(
    r"^(?P<label>(?:Fig\.|Figure|Table|TABLE)\s*(?:\d+|[IVX]+))(?:[.:]\s*(?P<rest>\S.*)|\s*$)"
)
CONTINUATION = re.compile(r"^Cont(inued)?\.?$", re.IGNORECASE)

# A formal statement opens a paragraph with its kind, its number and a full stop, set in a
# font other than the body's ("Theorem 1.", "Remark 2."). A proof has no number. A bare
# "Remark" (a table's column header) or "lemma 1, the..." in running text is not one.
STATEMENT = re.compile(
    r"^(?:(?P<kind>Theorem|Lemma|Proposition|Corollary|Definition|Assumption|Remark)\s+(?P<number>\d+)"
    r"|(?P<proof>Proof))\s*\."
)
PROVABLE = ("Theorem", "Lemma", "Proposition", "Corollary")


def parse_structure(pdf: Path) -> PaperStructure:
    lines = _read_lines(pdf)
    body_font = _body_font(lines)
    return PaperStructure(
        statements=tuple(_statements(lines, body_font)),
        captions=tuple(_captions(lines)),
    )


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
                    spans = tuple(
                        Span(s["text"], s["font"], round(s["size"], 1), bool(s["flags"] & 1))
                        for s in line["spans"]
                    )
                    if "".join(s.text for s in spans).strip():
                        lines.append(Line(index + 1, spans))
    return lines


def _body_font(lines: list[Line]) -> str:
    """The body is whichever font carries the most characters."""
    weight: Counter[str] = Counter()
    for line in lines:
        for span in line.spans:
            weight[span.font] += len(span.text)
    return weight.most_common(1)[0][0]


def _statements(lines: list[Line], body_font: str) -> Iterator[Statement]:
    last_provable: str | None = None  # a proof belongs to the nearest statement before it
    for line in lines:
        match = STATEMENT.match(line.text)
        if not match or line.font == body_font:
            continue
        if match["proof"]:
            yield Statement(line.page, "Proof", proves=last_provable)
            continue
        label = f"{match['kind']} {match['number']}"
        if match["kind"] in PROVABLE:
            last_provable = label
        yield Statement(line.page, label)


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
