"""Quality eval runner — produce a reply, judge it, gate on the score.

Replies are produced by a SINGLE completion using the live system prompt
(identity.build_system_prompt), so the eval directly exercises the agent's
self-evolved instructions with no side effects (no CRM writes, no emails, no
reflection). Results append to data/evals/quality_history.jsonl.

Run:  python -m evals.quality_runner
"""
import asyncio
import json
import os
import time

from agent import identity
import agent.tools  # noqa: F401 — ensure tool/instruction state is initialized
from llm.router import complete
from evals.judge import judge
from evals.quality_scenarios import QUALITY_SCENARIOS

HISTORY_PATH = "./data/evals/quality_history.jsonl"


async def _produce(message: str) -> str:
    system = identity.build_system_prompt()
    messages = [{"role": "system", "content": system}, {"role": "user", "content": message}]
    try:
        return await complete(messages, task_type="general", max_tokens=450)
    except Exception as e:
        return f"__error__: {e}"


async def run_quality(verbose: bool = True) -> dict:
    results = []
    for sc in QUALITY_SCENARIOS:
        answer = await _produce(sc["message"])
        try:
            verdict = await judge(sc["message"], answer, sc["rubric"])
            score = verdict["score"]
            reasons = verdict["reasons"]
        except Exception as e:
            score, reasons = 0, f"judge error: {e}"
        passed = score >= sc.get("min_score", 3)
        results.append({"name": sc["name"], "score": score,
                        "min_score": sc.get("min_score", 3),
                        "passed": passed, "reasons": reasons})
        if verbose:
            mark = "PASS" if passed else "FAIL"
            print(f"[{mark}] {sc['name']}: score={score}/5 (min {sc.get('min_score', 3)}) — {reasons}")

    passed_n = sum(1 for r in results if r["passed"])
    summary = {
        "ts": time.time(),
        "total": len(results),
        "passed": passed_n,
        "pass_rate": round(passed_n / max(len(results), 1), 3),
        "avg_score": round(sum(r["score"] for r in results) / max(len(results), 1), 2),
        "scores": {r["name"]: r["score"] for r in results},
        "results": results,
    }

    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    if verbose:
        print(f"\nQUALITY: {passed_n}/{len(results)} passed, avg {summary['avg_score']}/5")
    return summary


if __name__ == "__main__":
    asyncio.run(run_quality())
