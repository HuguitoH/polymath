import math
from dataclasses import dataclass
from datetime import UTC, datetime

from polymath.kernel.events import Event, Source
from polymath.kernel.store import Candidate

# Decay constants in days, per source. Larger tau = slower forgetting.
# News is worthless within a week; a hard-won insight should persist for years.
DECAY_TAU_DAYS: dict[Source, float] = {
    Source.NEWS: 3.0,
    Source.CHAT: 45.0,
    Source.DRAWING: 180.0,
    Source.QUEST: 90.0,
}
DEFAULT_TAU_DAYS = 30.0


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Relevance policy. Tunable from logged outcomes, not hardcoded in SQL."""

    similarity: float = 0.60
    salience: float = 0.25
    recency: float = 0.15


@dataclass(frozen=True, slots=True)
class ScoredEvent:
    event: Event
    score: float
    similarity: float
    recency: float


def _recency(event: Event, now: datetime) -> float:
    """Exponential decay of relevance with age, with a per-source time constant."""
    tau = DECAY_TAU_DAYS.get(event.source, DEFAULT_TAU_DAYS)
    age_days = (now - event.occurred_at).total_seconds() / 86_400.0
    return math.exp(-max(age_days, 0.0) / tau)


def score_candidates(
    candidates: list[Candidate],
    *,
    weights: ScoringWeights | None = None,
    now: datetime | None = None,
) -> list[ScoredEvent]:
    """Rank candidates by relevance, freshness and importance combined."""
    w = weights or ScoringWeights()
    reference = now or datetime.now(UTC)

    scored = []
    for candidate in candidates:
        similarity = 1.0 - candidate.distance
        recency = _recency(candidate.event, reference)
        total = (
            w.similarity * similarity + w.salience * candidate.event.salience + w.recency * recency
        )
        scored.append(
            ScoredEvent(
                event=candidate.event,
                score=total,
                similarity=similarity,
                recency=recency,
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
