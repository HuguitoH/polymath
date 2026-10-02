"""PDF structure: headings, formal statements and captions.

The parser reports what the document is. What is worth indexing is decided by the indexer.
"""

from dataclasses import dataclass
from pathlib import Path


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


def parse_structure(pdf: Path) -> PaperStructure:
    raise NotImplementedError
