"""Eval suite entrypoints."""

from __future__ import annotations

from pathlib import Path

from patchpilot.evals.harness import run_smoke_eval


async def run_suite(
    name: str,
    repo: Path,
    *,
    model_provider: str = "openrouter",
    model: str | None = None,
    live_eval: bool = False,
) -> dict:
    if name != "smoke":
        raise ValueError(f"Unknown eval suite: {name}")
    return await run_smoke_eval(repo, model_provider=model_provider, model=model, live_eval=live_eval)
