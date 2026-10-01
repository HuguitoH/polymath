from datetime import datetime, timedelta, timezone

from polymath.kernel.events import Event, Modality, Source
from polymath.kernel.retrieval import score_candidates
from polymath.kernel.store import Candidate

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _candidate(source: Source, age_days: int, distance: float) -> Candidate:
    return Candidate(
        event=Event(
            source=source,
            modality=Modality.TEXT,
            content="x",
            occurred_at=NOW - timedelta(days=age_days),
        ),
        distance=distance,
    )


def test_old_news_loses_to_older_insight() -> None:
    """Equal similarity, but news decays far faster than a chat insight."""
    news = _candidate(Source.NEWS, age_days=10, distance=0.2)
    insight = _candidate(Source.CHAT, age_days=30, distance=0.2)

    ranked = score_candidates([news, insight], now=NOW)

    assert ranked[0].event.source is Source.CHAT
