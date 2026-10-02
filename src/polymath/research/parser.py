"""PDF structure: headings, formal statements and captions.

The parser reports what the document is. What is worth indexing is decided by the indexer.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import groupby
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
class Paragraph:
    page_start: int
    page_end: int
    section: tuple[str, ...]  # heading titles, outermost first
    text: str  # line-break hyphens removed, running headers dropped


@dataclass(frozen=True)
class PaperStructure:
    headings: tuple[Heading, ...] = ()
    statements: tuple[Statement, ...] = ()
    captions: tuple[Caption, ...] = ()
    paragraphs: tuple[Paragraph, ...] = ()
    page_labels: tuple[str | None, ...] = ()  # printed page per PDF page, index 0 = page 1


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
        """The line as read, without superscripts (citations such as "Lemma 1.²⁴", footnotes).

        A removed superscript can be the only thing separating two words ("1.²⁴Given"),
        so it leaves a space behind when a word follows it.
        """
        parts: list[str] = []
        dropped = False
        for span in self.spans:
            if span.superscript:
                dropped = True
                continue
            if dropped and span.text[:1].isalnum() and parts and not parts[-1].endswith(" "):
                parts.append(" ")
            parts.append(span.text)
            dropped = False
        return "".join(parts).strip()

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
    lines, page_labels = _read_document(pdf)
    body = _body_style(lines)
    headed = _headings(lines, body)
    return PaperStructure(
        headings=tuple(heading for _, heading in headed),
        statements=tuple(_statements(lines, body.font)),
        captions=tuple(_captions(lines)),
        paragraphs=tuple(_paragraphs(lines, headed)),
        page_labels=page_labels,
    )


def _read_document(pdf: Path) -> tuple[list[Line], tuple[str | None, ...]]:
    """Every text line, whatever its font (IEEE sets captions in the body font),
    and the printed label of each page ("455"), if the PDF defines them.

    The only function that touches PyMuPDF, whose type hints are partial;
    everything after this boundary is strictly typed.
    """
    lines: list[Line] = []
    labels: list[str | None] = []
    block_id = 0
    with pymupdf.open(pdf) as doc:  # type: ignore[no-untyped-call]
        for index in range(doc.page_count):
            page = doc.load_page(index)
            labels.append(page.get_label() or None)
            layout: dict[str, Any] = page.get_text("dict")
            for block in layout["blocks"]:
                block_id += 1
                for line in block.get("lines", []):
                    spans = tuple(_span(s) for s in line["spans"])
                    if "".join(s.text for s in spans).strip():
                        lines.append(Line(index + 1, block_id, spans))
    return lines, tuple(labels)


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


def _headings(lines: list[Line], body: Style) -> list[tuple[list[Line], Heading]]:
    """Headings are set apart from the body; which ones, and at what level, depends on the paper.

    Front matter (title, authors, abstract) ends where "Introduction" starts. If the
    paper numbers its sections, the number gives the level, and an unnumbered heading
    ("References") must share the style of "Introduction". If it does not (Sage),
    "Introduction"'s font is level 1 and another font at least as large is level 2.
    """
    groups = _join_wrapped([line for line in lines if _set_apart(line, body)])
    candidates = [(group, _joined(group)) for group in groups]
    start = next(
        (i for i, (_, c) in enumerate(candidates) if bare_title(c.text) == "introduction"), None
    )
    if start is None:
        return []  # no anchor: report no headings rather than guess
    intro = candidates[start][1]
    numbered_paper = NUMBERED.match(intro.text) is not None
    headed: list[tuple[list[Line], Heading]] = []
    for group, line in candidates[start:]:
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
        headed.append((group, Heading(level, line.page, line.text)))
    return headed


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


def _join_wrapped(candidates: list[Line]) -> list[list[Line]]:
    """A heading that wraps continues in the same block and style, without a new number."""
    groups: list[list[Line]] = []
    for line in candidates:
        previous = groups[-1][-1] if groups else None
        if (
            previous is not None
            and previous.block == line.block
            and previous.style == line.style
            and not NUMBERED.match(line.text)
        ):
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def _joined(group: list[Line]) -> Line:
    """One logical line from the physical lines of a wrapped heading."""
    spans: list[Span] = []
    for line in group:
        if spans:
            spans.append(Span(" ", spans[-1].font, spans[-1].size, False))
        spans.extend(line.spans)
    return Line(group[0].page, group[0].block, tuple(spans))


def bare_title(text: str) -> str:
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


def _paragraphs(lines: list[Line], headed: list[tuple[list[Line], Heading]]) -> Iterator[Paragraph]:
    """Body text block by block, each under the headings that contain it.

    Skipped: front matter (before "Introduction"), heading and caption blocks, running
    headers and footers, and blocks that are not prose (display equations, figure labels).
    """
    # Lines are compared by identity: two lines can print the same text.
    opens = {id(group[0]): heading for group, heading in headed}
    in_heading = {id(line) for group, _ in headed for line in group}
    running = _running_lines(lines)
    vocabulary = _vocabulary(lines)
    path: list[Heading] = []
    for _, block in groupby(lines, key=lambda line: line.block):
        kept: list[Line] = []  # a block can hold a heading and the text that follows it
        for line in block:
            if id(line) in opens:
                yield from _paragraph(kept, path, vocabulary)
                heading = opens[id(line)]
                path, kept = [*(h for h in path if h.level < heading.level), heading], []
            elif id(line) not in in_heading and _running_key(line.text) not in running:
                kept.append(line)
        yield from _paragraph(kept, path, vocabulary)


def _paragraph(kept: list[Line], path: list[Heading], vocabulary: set[str]) -> Iterator[Paragraph]:
    if not path or not kept or CAPTION.match(kept[0].text):
        return  # front matter, nothing left, or a caption
    text = _unwrap([line.text for line in kept], vocabulary)
    if _is_prose(text):
        yield Paragraph(kept[0].page, kept[-1].page, tuple(h.title for h in path), text)


def _running_key(text: str) -> str:
    """Page numbers change from page to page; the rest of a running header does not."""
    return re.sub(r"\d+", "", text).strip().casefold()


def _running_lines(lines: list[Line]) -> set[str]:
    """Short lines repeated on three or more pages are running headers or footers."""
    pages: defaultdict[str, set[int]] = defaultdict(set)
    for line in lines:
        if len(line.text.split()) <= 12:
            pages[_running_key(line.text)].add(line.page)
    return {key for key, seen in pages.items() if len(seen) >= 3 or not key}


def _vocabulary(lines: list[Line]) -> set[str]:
    """Every word the paper prints whole, to decide how to undo a hyphen at a line break."""
    return {
        w.casefold() for line in lines for w in re.findall(r"[A-Za-z][A-Za-z-]*[A-Za-z]", line.text)
    }


def _unwrap(texts: list[str], vocabulary: set[str]) -> str:
    """Join a block's lines. "velo-" + "city" is "velocity"; "path-" + "following" keeps its
    hyphen if the paper prints "path-following" elsewhere and never "pathfollowing"."""
    joined = texts[0]
    for text in texts[1:]:
        left = re.search(r"([A-Za-z]+)-$", joined)
        right = re.match(r"([a-z]+)", text)
        if left and right:
            whole = (left[1] + right[1]).casefold()
            hyphenated = f"{left[1]}-{right[1]}".casefold()
            keep = hyphenated in vocabulary and whole not in vocabulary
            joined = (joined if keep else joined[:-1]) + text
        else:
            joined = f"{joined} {text}"
    return " ".join(joined.split())


def _is_prose(text: str) -> bool:
    """Sentences, not symbols: enough real words, mostly letters."""
    visible = text.replace(" ", "")
    words = re.findall(r"\b[a-z]{3,}\b", text)
    return len(words) >= 5 and sum(c.isalpha() for c in visible) >= 0.6 * len(visible)
