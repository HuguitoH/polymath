import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Fragment:
    """A labelled piece of context for the brief. The model composes; it never invents."""

    label: str
    body: str


class BriefSource(Protocol):
    """Anything that contributes context to the morning brief."""

    name: str

    async def fetch(self) -> Fragment: ...


class WeatherSource:
    """Open-Meteo. No API key, no auth, no account."""

    name = "weather"

    def __init__(self, client: httpx.AsyncClient, lat: float, lon: float) -> None:
        self._client = client
        self._lat = lat
        self._lon = lon

    async def fetch(self) -> Fragment:
        response = await self._client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": self._lat,
                "longitude": self._lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Europe/Madrid",
                "forecast_days": 1,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        daily = response.json()["daily"]
        return Fragment(
            label="tiempo",
            body=(
                f"high {round(daily['temperature_2m_max'][0])}, "
                f"low {round(daily['temperature_2m_min'][0])}, "
                f"probabilidad de lluvia {daily['precipitation_probability_max'][0]}%"
            ),
        )


class FeedSource:
    """RSS/Atom feeds, trimmed to headlines."""

    name = "feeds"

    def __init__(self, client: httpx.AsyncClient, urls: list[str], limit: int = 6) -> None:
        self._client = client
        self._urls = urls
        self._limit = limit

    async def fetch(self) -> Fragment:
        import feedparser

        headlines: list[str] = []
        for url in self._urls:
            try:
                response = await self._client.get(
                    url,
                    timeout=10.0,
                    follow_redirects=True,
                    headers={"User-Agent": "polymath/0.1 (personal brief)"},
                )
                response.raise_for_status()
            except Exception:
                logger.warning("feed %s failed", url, exc_info=True)
                continue
            parsed = feedparser.parse(response.text)
            headlines.extend(entry.title for entry in parsed.entries[: self._limit])

        return Fragment(label="titulares", body="\n".join(f"- {h}" for h in headlines))
