"""Prompt assets, composed stable-parts-first so the KV cache prefix is reused."""

from functools import lru_cache
from pathlib import Path

PROMPTS = Path(__file__).parent

# Bump whenever any prompt file changes. Stored in event metadata so a bad
# output can be traced back to the prompt that produced it.
VERSION = "2026-09-05f"


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()


def compose(task: str, extra: str | None = None) -> str:
    """Stable parts first for KV reuse; per-run instructions appended last."""
    parts = [_read("identity"), _read("rules"), _read(task)]
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)
