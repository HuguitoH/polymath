"""Brief verification: what ships and what gets regenerated."""

import pytest

from polymath.kernel.llm import Completion, Tier
from polymath.workflows.brief import QUALITY_FLOOR, Draft, Verdict, verify
from polymath.workflows.sources import Fragment


@pytest.mark.parametrize(
    ("score", "issue", "acceptable"),
    [
        (9.0, "", True),
        (QUALITY_FLOOR, "", True),
        (2.0, "", False),  # low score rejects even with no issue named
        (9.0, "claims Hugo watched a talk", False),  # a named issue outweighs the score
    ],
)
def test_verdict_needs_both_a_passing_score_and_no_issue(
    score: float, issue: str, acceptable: bool
) -> None:
    assert Verdict(score=score, issue=issue).is_acceptable is acceptable


class _LLMThatMustNotRun:
    async def complete(
        self, *, system: str, user: str, tier: Tier, max_tokens: int | None = None
    ) -> Completion:
        raise AssertionError("the deterministic guard should have rejected the draft first")


async def test_invented_memory_is_rejected_without_calling_the_model() -> None:
    fragments = [Fragment(label="tiempo", body="high 20, low 12")]
    draft = Draft(text="Morning, Hugo. You mentioned you'd watch for this.", tokens=12)

    verdict = await verify(_LLMThatMustNotRun(), fragments, draft)

    assert not verdict.is_acceptable
    assert "you mentioned" in verdict.issue.lower()
