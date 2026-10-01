from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Protocol

import litellm

from polymath.config import Settings


class LLMError(RuntimeError):
    """Raised when a completion fails or comes back empty."""


class Tier(StrEnum):
    """What kind of thinking a call site needs, independent of which model provides it."""

    FAST = auto()
    REASONING = auto()
    FRONTIER = auto()


@dataclass(frozen=True, slots=True)
class TierConfig:
    model: str
    max_tokens: int
    temperature: float
    local: bool = True


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    tier: Tier
    model: str
    prompt_tokens: int
    completion_tokens: int


class LLM(Protocol):
    """What the kernel needs from any completion provider."""

    async def complete(
        self, *, system: str, user: str, tier: Tier, max_tokens: int | None = None
    ) -> Completion: ...


class LiteLLM:
    """Completion provider routing tiers to concrete models via litellm."""

    def __init__(self, settings: Settings) -> None:
        self._api_base = settings.ollama_base_url
        self._tiers: dict[Tier, TierConfig] = {
            # Everyday generation: whichever model .env points at.
            Tier.FAST: TierConfig(
                model=settings.model,
                max_tokens=2000,
                temperature=0.3,
                local=settings.model_is_local,
            ),
            # Local thinking model on the GPU; its prompts never leave the machine.
            Tier.REASONING: TierConfig(
                model=settings.reasoning_model,
                max_tokens=2048,
                temperature=0.7,
                local=True,
            ),
            # Strongest remote model, for the rare call that needs it.
            Tier.FRONTIER: TierConfig(
                model=settings.frontier_model,
                max_tokens=4096,
                temperature=0.7,
                local=False,
            ),
        }

    async def complete(
        self, *, system: str, user: str, tier: Tier, max_tokens: int | None = None
    ) -> Completion:
        config = self._tiers[tier]
        kwargs: dict[str, object] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens or config.max_tokens,
            "temperature": config.temperature,
        }
        if config.local:
            kwargs["api_base"] = self._api_base

        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            raise LLMError(f"{tier} completion failed: {exc}") from exc

        text = response.choices[0].message.content
        if not text or not text.strip():
            raise LLMError(f"{tier} returned empty content")

        usage = response.usage
        return Completion(
            text=text.strip(),
            tier=tier,
            model=config.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
