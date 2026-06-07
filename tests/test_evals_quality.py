"""Tests for the LLM-as-judge quality harness.

- The judge's parsing/clamping is unit-tested offline (monkeypatched LLM).
- The full live eval gate is opt-in: it only runs when RUN_LLM_EVALS=1 and an API
  key is configured, so default/offline CI stays fast and green while real CI can
  flip the flag to guard against self-evolution regressions.
"""
import asyncio
import os

import pytest

from config import config
from evals import judge as judge_mod


def test_judge_parses_and_clamps(monkeypatch):
    async def fake_complete(messages, task_type="general", max_tokens=250):
        return '```json\n{"score": 9, "reasons": "great"}\n```'
    monkeypatch.setattr(judge_mod, "complete", fake_complete)
    out = asyncio.run(judge_mod.judge("q", "a", "rubric"))
    assert out["score"] == 5  # clamped to max
    assert out["reasons"] == "great"


def test_judge_handles_bad_score(monkeypatch):
    async def fake_complete(messages, task_type="general", max_tokens=250):
        return '{"score": "not-a-number", "reasons": "x"}'
    monkeypatch.setattr(judge_mod, "complete", fake_complete)
    out = asyncio.run(judge_mod.judge("q", "a", "rubric"))
    assert out["score"] == 0


_LIVE = (os.getenv("RUN_LLM_EVALS", "").strip().lower() in ("1", "true", "yes")
         and (config.groq_api_key or config.openai_api_key or config.gemini_api_key))


@pytest.mark.skipif(not _LIVE, reason="LLM evals are opt-in: set RUN_LLM_EVALS=1 with an API key")
def test_quality_evals_pass():
    from evals.quality_runner import run_quality
    summary = asyncio.run(run_quality(verbose=False))
    failed = [r["name"] for r in summary["results"] if not r["passed"]]
    assert not failed, f"Quality regressions: {failed} (scores: {summary['scores']})"
