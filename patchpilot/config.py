"""Runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


class PatchPilotConfig(BaseModel):
    repo: Path = Field(default_factory=Path.cwd)
    openrouter_api_key: str | None = None
    model: str = "anthropic/claude-sonnet-4.5"
    base_url: str = "https://openrouter.ai/api/v1"
    trace_dir: Path = Path(".patchpilot/traces")
    allow_write: bool = False
    allow_exec: bool = False
    allow_high_risk_exec: bool = False
    max_repair_attempts: int = 3
    max_tool_calls: int = 80
    max_model_calls: int = 20
    max_diff_lines: int = 200
    command_timeout_seconds: int = 120

    @classmethod
    def from_env(cls, repo: Path | None = None, **overrides: object) -> "PatchPilotConfig":
        data: dict[str, object] = {
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "model": os.getenv("PATCHPILOT_MODEL", cls.model),
            "base_url": os.getenv("PATCHPILOT_BASE_URL", cls.base_url),
        }
        if repo is not None:
            data["repo"] = repo
        data.update(overrides)
        return cls(**data)

