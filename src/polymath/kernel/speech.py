"""Text to speech. The brief writes a file; conversation will stream later."""

import asyncio
import logging
from pathlib import Path
from typing import Protocol

import soundfile as sf

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
KOKORO_REPO = "hexgrad/Kokoro-82M"


class SpeechError(RuntimeError):
    """Raised when synthesis fails or produces no audio."""


class Synthesizer(Protocol):
    """What the kernel needs from any TTS provider."""

    voice: str

    async def to_file(self, text: str, path: Path) -> Path: ...


class KokoroSynthesizer:
    """Kokoro-82M. Small enough for CPU; loaded once and reused."""

    def __init__(self, voice: str = "af_heart", lang_code: str = "a") -> None:
        self.voice = voice
        self._lang_code = lang_code
        self._pipeline = None  # built lazily: import cost is significant

    def _ensure_pipeline(self) -> object:
        if self._pipeline is None:
            from kokoro import KPipeline

            # Phonemizer configures its own logger when kokoro imports it,
            # after our logging setup has run. Silence it here instead.
            phonemizer_logger = logging.getLogger("phonemizer")
            phonemizer_logger.handlers.clear()
            phonemizer_logger.propagate = False
            phonemizer_logger.setLevel(logging.CRITICAL)

            self._pipeline = KPipeline(lang_code=self._lang_code, repo_id=KOKORO_REPO)
        return self._pipeline

    def _synthesize(self, text: str, path: Path) -> Path:
        """Blocking. Runs in a thread so the event loop stays free."""
        import numpy as np

        pipeline = self._ensure_pipeline()
        chunks = [audio for _, _, audio in pipeline(text, voice=self.voice)]  # type: ignore[operator]
        if not chunks:
            raise SpeechError("kokoro produced no audio")

        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, np.concatenate(chunks), SAMPLE_RATE)
        return path

    async def to_file(self, text: str, path: Path) -> Path:
        if not text.strip():
            raise SpeechError("cannot synthesize empty text")
        return await asyncio.to_thread(self._synthesize, text, path)
