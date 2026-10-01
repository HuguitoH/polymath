import pytest

from polymath.kernel.events import Event, Modality, Source


class FakeEmbedder:
    model_name = "fake"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        return [float(len(text) % 7)] * self.dimensions


@pytest.mark.asyncio
async def test_append_then_find(store) -> None:
    event = Event(
        source=Source.CHAT,
        modality=Modality.TEXT,
        content="el backpressure en colas es control de flujo",
    )
    await store.append(event)

    found = await store.search_similar("control de flujo", limit=5)

    assert any(c.event.id == event.id for c in found)
