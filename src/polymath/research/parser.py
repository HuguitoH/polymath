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
class Style:
    font: str
    size: float


@dataclass(frozen=True)
class Line:
    page: int
    block: int  # lines of one PyMuPDF block belong together (a heading wrapped over two lines)
    spans: tuple[Span, ...]

    @property
    def text(self) -> str:
        """The line as read, without superscripts (citations such as "Lemma 1.²⁴", footnotes)."""
        return "".join(s.text for s in self.spans if not s.superscript).strip()

    @property
    def font(self) -> str:
        """The font the line opens with: a statement label ("Theorem 1.") is set apart."""
        return self.spans[0].font

    @property
    def style(self) -> Style:
        """The font and size that carry most of the line's characters."""
        weight: Counter[Style] = Counter()
        for span in self.spans:
            if not span.superscript:
                weight[Style(span.font, span.size)] += len(span.text.strip())
        if not weight:  # a line made only of superscripts
            return Style(self.spans[0].font, self.spans[0].size)
        return weight.most_common(1)[0][0]


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

# "2.1. Title", "4.1 Title": the number gives the level.
NUMBERED = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+[A-Za-z]")

# Some typesetters' fonts draw symbols with the code of another character. Each entry is
# keyed by the exact font name and checked against a rendering of the page, because the
# same character means different things in different fonts.
GLYPHS: dict[str, dict[int, str]] = {
    # Elsevier maths font. Checked: "PIDþFF" is PID+FF, "H1" is H∞, "Tel.: þ44" is +44.
    "AdvMacMthSyN": str.maketrans({"þ": "+", "¼": "=", "ð": "(", "Þ": ")", "1": "∞"}),
}


def parse_structure(pdf: Path) -> PaperStructure:
    lines = _read_lines(pdf)
    body = _body_style(lines)
    return PaperStructure(
        headings=tuple(_headings(lines, body)),
        statements=tuple(_statements(lines, body.font)),
        captions=tuple(_captions(lines)),
    )


def _read_lines(pdf: Path) -> list[Line]:
    """Every text line, whatever its font: IEEE sets captions in the body font.

    The only function that touches PyMuPDF, whose type hints are partial;
    everything after this boundary is strictly typed.
    """
    lines: list[Line] = []
    block_id = 0
    with pymupdf.open(pdf) as doc:  # type: ignore[no-untyped-call]
        for index in range(doc.page_count):
            layout: dict[str, Any] = doc.load_page(index).get_text("dict")
            for block in layout["blocks"]:
                block_id += 1
                for line in block.get("lines", []):
                    spans = tuple(_span(s) for s in line["spans"])
                    if "".join(s.text for s in spans).strip():
                        lines.append(Line(index + 1, block_id, spans))
    return lines


def _span(raw: dict[str, Any]) -> Span:
    text: str = raw["text"]
    glyphs = GLYPHS.get(raw["font"])
    return Span(
        text=text.translate(glyphs) if glyphs else text,
        font=raw["font"],
        size=round(raw["size"], 1),
        superscript=bool(raw["flags"] & 1),
    )


def _body_style(lines: list[Line]) -> Style:
    """The body is whichever font, and whichever size, carries the most characters."""
    fonts: Counter[str] = Counter()
    sizes: Counter[float] = Counter()
    for line in lines:
        for span in line.spans:
            fonts[span.font] += len(span.text)
            sizes[span.size] += len(span.text)
    return Style(fonts.most_common(1)[0][0], sizes.most_common(1)[0][0])


def _headings(lines: list[Line], body: Style) -> Iterator[Heading]:
    """Headings are set apart from the body; which ones, and at what level, depends on the paper.

    Front matter (title, authors, abstract) ends where "Introduction" starts. If the
    paper numbers its sections, the number gives the level, and an unnumbered heading
    ("References") must share the style of "Introduction". If it does not (Sage),
    "Introduction"'s font is level 1 and another font at least as large is level 2.
    """
    candidates = _join_wrapped([line for line in lines if _set_apart(line, body)])
    intro = next((c for c in candidates if _bare_title(c.text) == "introduction"), None)
    if intro is None:
        return  # no anchor: report no headings rather than guess
    numbered_paper = NUMBERED.match(intro.text) is not None
    for line in candidates[candidates.index(intro) :]:
        style, numbered = line.style, NUMBERED.match(line.text)
        if numbered_paper and numbered:
            level = numbered["number"].count(".") + 1
        elif numbered_paper:
            if style != intro.style:
                continue
            level = 1
        elif style.font == intro.style.font:
            level = 1
        elif style.size >= intro.style.size:
            level = 2
        else:
            continue
        yield Heading(level, line.page, line.text)


def _set_apart(line: Line, body: Style) -> bool:
    """A heading candidate: short, wordy, not body text, not a caption, statement or equation."""
    text = line.text
    visible = text.replace(" ", "")
    return (
        line.style.font != body.font
        and line.style.size >= body.size - 0.5
        and 2 < len(text) <= 150
        and sum(c.isalpha() for c in visible) >= 0.6 * len(visible)
        and "=" not in text
        and not CAPTION.match(text)
        and not STATEMENT.match(text)
    )


def _join_wrapped(candidates: list[Line]) -> list[Line]:
    """A heading that wraps continues in the same block and style, without a new number."""
    joined: list[Line] = []
    for line in candidates:
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and previous.block == line.block
            and previous.style == line.style
            and not NUMBERED.match(line.text)
        ):
            separator = Span(" ", previous.spans[-1].font, previous.spans[-1].size, False)
            joined[-1] = Line(
                previous.page, previous.block, (*previous.spans, separator, *line.spans)
            )
        else:
            joined.append(line)
    return joined


def _bare_title(text: str) -> str:
    """ "1. Introduction" and "INTRODUCTION" are the same heading."""
    return re.sub(r"^[\dIVX.]+\s+", "", text).strip().casefold()


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
