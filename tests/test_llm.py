"""Tier routing: each tier must reach the model configured for it."""

from types import SimpleNamespace

import litellm
import pytest

from polymath.config import Settings
from polymath.kernel.llm import LiteLLM, LLMError, Tier

SETTINGS = Settings(
    db_password="unused",
    ollama_base_url="http://ollama.test:11434",
    model="deepseek/deepseek-chat",
    model_is_local=False,
    reasoning_model="ollama_chat/qwen3:4b",
    frontier_model="anthropic/claude-sonnet-4-5",
)


def _response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace the network call; record what would have been sent."""
    calls: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls.update(kwargs)
        return _response("ok")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return calls


@pytest.mark.parametrize(
    ("tier", "model", "sent_to_local_ollama"),
    [
        (Tier.FAST, "deepseek/deepseek-chat", False),
        (Tier.REASONING, "ollama_chat/qwen3:4b", True),
        (Tier.FRONTIER, "anthropic/claude-sonnet-4-5", False),
    ],
)
async def test_each_tier_routes_to_its_configured_model(
    captured: dict[str, object], tier: Tier, model: str, sent_to_local_ollama: bool
) -> None:
    completion = await LiteLLM(SETTINGS).complete(system="s", user="u", tier=tier)

    assert captured["model"] == model
    assert completion.model == model
    assert ("api_base" in captured) is sent_to_local_ollama


async def test_empty_completion_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def blank(**_: object) -> SimpleNamespace:
        return _response("   ")

    monkeypatch.setattr(litellm, "acompletion", blank)

    with pytest.raises(LLMError, match="empty"):
        await LiteLLM(SETTINGS).complete(system="s", user="u", tier=Tier.FAST)
