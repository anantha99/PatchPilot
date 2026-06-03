"""Eval suite entrypoints."""

from __future__ import annotations

from pathlib import Path

from patchpilot.evals.harness import run_smoke_eval


async def run_suite(name: str, repo: Path) -> dict:
    if name != "smoke":
        raise ValueError(f"Unknown eval suite: {name}")
    return await run_smoke_eval(repo)
