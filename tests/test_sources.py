import httpx
import pytest

from polymath.workflows.sources import FeedSource, SourceError


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Temporary failure in name resolution", request=request)


async def test_feed_source_raises_when_every_feed_fails() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_unreachable)) as client:
        source = FeedSource(client, ["https://a.test/feed", "https://b.test/feed"])

        with pytest.raises(SourceError, match="every feed failed"):
            await source.fetch()
