"""Morning brief workflow.

A deterministic pipeline, not an agent: the steps are known in advance, so
each one is a plain function and the orchestrator only sequences them.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from polymath.kernel.events import Event, Modality, Source
from polymath.kernel.llm import LLM, Tier
from polymath.kernel.retrieval import score_candidates
from polymath.kernel.speech import SpeechError, Synthesizer
from polymath.kernel.store import EventStore
from polymath.prompts import VERSION, compose
from polymath.workflows.sources import BriefSource, Fragment

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 30.0
QUALITY_FLOOR = 7.0
RECALL_THRESHOLD = 0.55
RECALL_LIMIT = 2
DRAFT_TOKEN_BUDGET = 400
VERDICT_TOKEN_BUDGET = 120
BRIEF_SALIENCE = 0.3

RECALL_LABEL = "recall"

NO_RECALL_NOTE = (
    "Today there is no record of past conversations with Hugo. "
    "Write the brief without referring to anything he has said before."
)

VERIFIER_PROMPT = (
    "You check a briefing against its source data.\n"
    "For every claim in the briefing, decide whether the data supports it.\n"
    "Treat any claim about Hugo as unsupported unless it appears in the "
    "data: what he said, did, works on, watches for, or finds interesting. "
    "Hedged phrasing counts as a claim.\n"
    "Reply on two lines:\n"
    "SCORE: <0-10>\n"
    "ISSUE: <one line naming the unsupported claim, or 'none'>"
)

_SCORE_PATTERN = re.compile(r"SCORE:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_ISSUE_PATTERN = re.compile(r"ISSUE:\s*(.+)", re.IGNORECASE)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MARKDOWN_BLOCK = re.compile(r"^#{1,6}\s+|^\s*[-*\u2022]\s+", re.MULTILINE)

# Phrases the model reaches for when it has no personal data but the brief
# asks for something personal. A same-size verifier does not catch these,
# so they are blocked deterministically.
_UNSUPPORTED_CLAIM = re.compile(
    r"\b(you'?ll want|you'?d want|your kind of|hit your interest|"
    r"you'?re into|kind of thing you|that'?s one you|you said|"
    r"you mentioned|you'?d watch|for you to see)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The verifier's judgement of a draft."""

    score: float
    issue: str

    @property
    def is_acceptable(self) -> bool:
        return self.score >= QUALITY_FLOOR and not self.issue


@dataclass(frozen=True, slots=True)
class Draft:
    """A candidate brief and what it cost to produce."""

    text: str
    tokens: int


# --- step 1: gather --------------------------------------------------------


async def _fetch_one(source: BriefSource) -> Fragment | None:
    """One failing source must never take down the brief."""
    try:
        return await asyncio.wait_for(source.fetch(), timeout=FETCH_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("brief source failed", extra={"source": source.name}, exc_info=True)
        return None


async def _recall(store: EventStore, fragments: list[Fragment]) -> Fragment | None:
    """Surface things Hugo said that connect to today's items.

    Returns None when nothing clears the threshold. A forced link every
    morning reads as mechanical; absence is what makes the hits land.
    """
    query = " ".join(fragment.body for fragment in fragments)
    if not query.strip():
        return None

    candidates = await store.search_similar(query, limit=20, sources=frozenset({Source.CHAT}))
    relevant = [
        scored for scored in score_candidates(candidates) if scored.score > RECALL_THRESHOLD
    ][:RECALL_LIMIT]

    if not relevant:
        return None

    return Fragment(
        label=RECALL_LABEL,
        body="\n".join(f"- {scored.event.content[:200]}" for scored in relevant),
    )


async def gather_context(sources: list[BriefSource], store: EventStore) -> list[Fragment]:
    """Collect today's data plus anything remembered that connects to it."""
    results = await asyncio.gather(*(_fetch_one(source) for source in sources))
    fragments = [fragment for fragment in results if fragment is not None]

    if not fragments:
        raise RuntimeError("every brief source failed; nothing to compose")

    recalled = await _recall(store, fragments)
    if recalled is not None:
        fragments.append(recalled)

    logger.info(
        "context gathered",
        extra={"fragments": [f.label for f in fragments]},
    )
    return fragments


# --- step 2: draft ---------------------------------------------------------


def as_data_block(fragments: list[Fragment]) -> str:
    """Tag the input so the model can tell instructions from data."""
    inner = "\n".join(
        f"<{fragment.label}>\n{fragment.body}\n</{fragment.label}>" for fragment in fragments
    )
    return f"<data>\n{inner}\n</data>"


def _system_prompt(fragments: list[Fragment]) -> str:
    """Only show instructions today's data can support."""
    has_recall = any(fragment.label == RECALL_LABEL for fragment in fragments)
    return compose("brief", None if has_recall else NO_RECALL_NOTE)


async def draft_brief(llm: LLM, fragments: list[Fragment], correction: str | None = None) -> Draft:
    """Write one candidate brief, optionally addressing a rejected attempt."""
    data = as_data_block(fragments)
    if correction:
        data = (
            f"{data}\n\nA previous draft was rejected: {correction}\n"
            "Write the briefing again without that claim."
        )

    completion = await llm.complete(
        system=_system_prompt(fragments),
        user=data,
        tier=Tier.FAST,
        max_tokens=DRAFT_TOKEN_BUDGET,
    )
    return Draft(text=completion.text, tokens=completion.completion_tokens)


# --- step 3: verify --------------------------------------------------------


async def _ask_verifier(llm: LLM, data: str, draft: Draft) -> Verdict:
    """Model-based check. Its failure never blocks delivery."""
    try:
        result = await llm.complete(
            system=VERIFIER_PROMPT,
            user=f"{data}\n\n<briefing>\n{draft.text}\n</briefing>",
            tier=Tier.FAST,
            max_tokens=VERDICT_TOKEN_BUDGET,
        )
    except Exception:
        logger.warning("verifier failed; shipping draft unchecked", exc_info=True)
        return Verdict(score=QUALITY_FLOOR, issue="")

    score_match = _SCORE_PATTERN.search(result.text)
    if score_match is None:
        logger.warning("verifier returned no score", extra={"reply": result.text[:120]})
        return Verdict(score=QUALITY_FLOOR, issue="")

    issue_match = _ISSUE_PATTERN.search(result.text)
    issue = issue_match.group(1).strip() if issue_match else ""
    return Verdict(
        score=float(score_match.group(1)),
        issue="" if issue.lower() == "none" else issue,
    )


def _scan_for_claims(draft: Draft, fragments: list[Fragment]) -> Verdict | None:
    """Deterministic guard against invented claims about Hugo.

    Only meaningful when nothing was recalled: with a recall fragment present,
    a reference to what he said is likely true and the model-based verifier
    is the right judge of that.
    """
    if any(fragment.label == RECALL_LABEL for fragment in fragments):
        return None

    normalised = draft.text.replace("\u2019", "'")
    match = _UNSUPPORTED_CLAIM.search(normalised)
    if match is None:
        return None
    return Verdict(score=0.0, issue=f"unsupported claim about Hugo: {match.group(0)}")


async def verify(llm: LLM, fragments: list[Fragment], draft: Draft) -> Verdict:
    """Judge a draft: cheap deterministic check first, model second."""
    hard_failure = _scan_for_claims(draft, fragments)
    if hard_failure is not None:
        return hard_failure
    return await _ask_verifier(llm, as_data_block(fragments), draft)


# --- step 4: persist and narrate -------------------------------------------


def for_speech(text: str) -> str:
    """Strip anything the prompt forbade but the model produced anyway."""
    text = _THINK_BLOCK.sub("", text)
    text = _MARKDOWN_BLOCK.sub("", text)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", ",").replace("\u2013", ",")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\s+([,.;:?!])", r"\1", text).strip()


async def persist(
    store: EventStore, draft: Draft, verdict: Verdict, fragments: list[Fragment]
) -> Event:
    """Record the brief as an event. Low salience: news decays in days."""
    event = Event(
        source=Source.NEWS,
        modality=Modality.TEXT,
        content=for_speech(draft.text),
        salience=BRIEF_SALIENCE,
        metadata={
            "kind": "morning_brief",
            "sources": [fragment.label for fragment in fragments],
            "prompt_version": VERSION,
            "tokens": draft.tokens,
            "quality_score": verdict.score,
            "quality_issue": verdict.issue,
        },
    )
    return await store.append(event)


async def narrate(synthesizer: Synthesizer | None, event: Event, audio_dir: Path) -> None:
    """Render the brief to audio. A readable brief beats no brief."""
    if synthesizer is None:
        return
    try:
        await synthesizer.to_file(event.content, audio_dir / f"{event.id}.wav")
    except SpeechError:
        logger.warning("speech synthesis failed", extra={"event_id": str(event.id)}, exc_info=True)


# --- orchestrator ----------------------------------------------------------


async def compose_brief(
    sources: list[BriefSource],
    llm: LLM,
    store: EventStore,
    audio_dir: Path,
    synthesizer: Synthesizer | None = None,
) -> Event:
    """Sequence the pipeline. Owns no work of its own."""
    fragments = await gather_context(sources, store)

    draft = await draft_brief(llm, fragments)
    verdict = await verify(llm, fragments, draft)

    if not verdict.is_acceptable:
        logger.info(
            "draft rejected; regenerating once",
            extra={"quality_score": verdict.score, "quality_issue": verdict.issue},
        )
        draft = await draft_brief(llm, fragments, correction=verdict.issue)
        verdict = await verify(llm, fragments, draft)
        if not verdict.is_acceptable:
            logger.warning(
                "second draft also rejected; shipping it anyway",
                extra={"quality_issue": verdict.issue},
            )

    event = await persist(store, draft, verdict, fragments)
    await narrate(synthesizer, event, audio_dir)

    logger.info(
        "brief composed",
        extra={
            "event_id": str(event.id),
            "quality_score": verdict.score,
            "tokens": draft.tokens,
            "characters": len(event.content),
        },
    )
    return event
