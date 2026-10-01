from polymath.kernel.events import Event, Modality, Source
from polymath.kernel.store import EventStore


def _chat(content: str) -> Event:
    return Event(source=Source.CHAT, modality=Modality.TEXT, content=content)


async def test_search_ranks_the_matching_event_first(store: EventStore) -> None:
    target = _chat("el backpressure en colas es control de flujo")
    distractor = _chat("el café de la mañana estaba frío")
    await store.append(target)
    await store.append(distractor)

    found = await store.search_similar(target.content, limit=2)

    # Fails if distances stop discriminating: with parallel vectors every
    # distance is 0 and the order is arbitrary.
    assert found[0].event.id == target.id
    assert found[0].distance < 1e-6
    assert found[1].distance > 0.5


async def test_source_filter_excludes_other_sources(store: EventStore) -> None:
    text = "titular de hoy"
    news = Event(source=Source.NEWS, modality=Modality.TEXT, content=text)
    chat = _chat(text)
    await store.append(news)
    await store.append(chat)

    found = await store.search_similar(text, limit=10, sources=frozenset({Source.CHAT}))

    # Same text, same vector: only the filter can tell them apart. Checking
    # that the chat event is present stops an empty result from passing.
    assert found[0].event.id == chat.id
    assert news.id not in {candidate.event.id for candidate in found}
