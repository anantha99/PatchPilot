"""Named eval suite entrypoints used by the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import httpx

from patchpilot.evals.harness import run_multifile_eval, run_smoke_eval

ProgressCallback = Callable[[dict[str, Any]], None]


async def run_suite(
    name: str,
    repo: Path,
    *,
    model_provider: str = "openrouter",
    model_profile: str | None = None,
    model: str | None = None,
    live_eval: bool = False,
    progress: ProgressCallback | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    if name == "smoke":
        return await run_smoke_eval(repo, model_provider=model_provider, model_profile=model_profile, model=model, live_eval=live_eval, progress=progress, model_transport=model_transport)
    if name in {"v2", "v2-multifile", "multifile"}:
        return await run_multifile_eval(repo, model_provider=model_provider, model_profile=model_profile, model=model, live_eval=live_eval, progress=progress, model_transport=model_transport)
    raise ValueError(f"Unknown eval suite: {name}")
