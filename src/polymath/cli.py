"""Command-line entry points for scheduled routines."""

import asyncio
import logging
import sys

import httpx

from polymath.config import Settings
from polymath.kernel.db import make_pool
from polymath.kernel.embedding import OllamaEmbedder
from polymath.kernel.llm import LiteLLM
from polymath.kernel.speech import KokoroSynthesizer
from polymath.kernel.store import EventStore
from polymath.observability.logs import configure as configure_logging
from polymath.workflows.brief import compose_brief
from polymath.workflows.sources import BriefSource, FeedSource, WeatherSource

configure_logging(service_name="polymath-brief")
logger = logging.getLogger("polymath.cli")

FEEDS = [
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://hnrss.org/frontpage",
    "https://www.quantamagazine.org/feed/",
    "https://spectrum.ieee.org/feeds/feed.rss",
]


async def _run_brief() -> int:
    settings = Settings()
    pool = make_pool(settings)
    await pool.open()
    try:
        async with httpx.AsyncClient() as client:
            store = EventStore(pool, OllamaEmbedder(settings, client))
            sources: list[BriefSource] = [
                WeatherSource(client, 40.4168, -3.7038),
                FeedSource(client, FEEDS),
            ]
            event = await compose_brief(
                sources,
                LiteLLM(settings),
                store,
                settings.audio_dir,
                KokoroSynthesizer(voice=settings.tts_voice),
            )
            print(event.content)
        return 0
    except Exception:
        logger.exception("brief failed")
        return 1
    finally:
        await pool.close()


def brief() -> None:
    """Entry point: polymath-brief"""
    sys.exit(asyncio.run(_run_brief()))
