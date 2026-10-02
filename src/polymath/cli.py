"""Command-line entry points for scheduled routines."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx

from polymath.config import Settings
from polymath.kernel.db import make_pool
from polymath.kernel.embedding import OllamaEmbedder
from polymath.kernel.llm import LiteLLM
from polymath.kernel.speech import KokoroSynthesizer
from polymath.kernel.store import EventStore
from polymath.observability.logs import configure as configure_logging
from polymath.research.ingest import IngestError, ingest_pdf
from polymath.research.store import PaperStore
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


async def _run_ingest(pdf: Path, citekey: str, title: str) -> int:
    settings = Settings()
    pool = make_pool(settings)
    await pool.open()
    try:
        async with httpx.AsyncClient() as client:
            store = PaperStore(pool, OllamaEmbedder(settings, client))
            outcome = await ingest_pdf(pdf, citekey, title, store)
            logger.info("paper ingested", extra={"citekey": citekey, "outcome": outcome})
            print(f"{citekey}: {outcome}")
        return 0
    except IngestError:
        logger.exception("ingest failed", extra={"citekey": citekey})
        return 1
    finally:
        await pool.close()


def ingest() -> None:
    """Entry point: polymath-ingest PDF --citekey KEY --title TITLE"""
    parser = argparse.ArgumentParser(description="Parse, chunk, embed and store one paper.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--citekey", required=True)
    parser.add_argument("--title", required=True, help="until Zotero supplies it")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run_ingest(args.pdf, args.citekey, args.title)))
