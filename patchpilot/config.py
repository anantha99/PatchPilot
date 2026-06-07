"""Runtime configuration for provider, budget, permission, and trace policy."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


DEFAULT_V2_MODEL = "minimax/minimax-m3"
DEFAULT_MODEL = DEFAULT_V2_MODEL
DEFAULT_MODEL_PROVIDER = "openrouter"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL_PROFILE = "v2-strong"
MINIMAX_MODEL_PREFIX = "minimax/"

MODEL_PROFILES = {
    "minimax": DEFAULT_V2_MODEL,
    "minimax-m3": DEFAULT_V2_MODEL,
    "v2-strong": DEFAULT_V2_MODEL,
}


class PatchPilotConfig(BaseModel):
    """Single source of truth for permissions, budgets, model, and trace paths."""

    repo: Path = Field(default_factory=Path.cwd)
    model_provider: str = DEFAULT_MODEL_PROVIDER
    openrouter_api_key: str | None = None
    model_profile: str = DEFAULT_MODEL_PROFILE
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    trace_dir: Path = Path(".patchpilot/traces")
    allow_write: bool = False
    allow_exec: bool = False
    allow_high_risk_exec: bool = False
    max_repair_attempts: int = 3
    max_tool_calls: int = 80
    max_model_calls: int = 80
    model_retry_attempts: int = 3
    model_retry_multiplier: float = 0.5
    model_retry_max_wait: float = 8.0
    model_rate_limit_calls: int = 30
    model_rate_limit_period_seconds: int = 60
    enable_prompt_cache: bool = True
    live_eval: bool = False
    blind_eval: bool = False
    max_diff_lines: int = 200
    command_timeout_seconds: int = 120

    @field_validator("model_provider")
    @classmethod
    def validate_model_provider(cls, value: str) -> str:
        if value != DEFAULT_MODEL_PROVIDER:
            raise ValueError("PatchPilot only supports the openrouter model provider")
        return value

    @classmethod
    def from_env(cls, repo: Path | None = None, **overrides: object) -> "PatchPilotConfig":
        dotenv = _read_dotenv(repo)
        model_profile = str(_env("PATCHPILOT_MODEL_PROFILE", dotenv, DEFAULT_MODEL_PROFILE))
        explicit_model = _env("PATCHPILOT_MODEL", dotenv, None)
        data: dict[str, object] = {
            "model_provider": _env("PATCHPILOT_MODEL_PROVIDER", dotenv, DEFAULT_MODEL_PROVIDER),
            "openrouter_api_key": _env("OPENROUTER_API_KEY", dotenv, None),
            "model_profile": model_profile,
            "model": resolve_model_profile(model_profile, explicit_model, dotenv),
            "base_url": _env("PATCHPILOT_BASE_URL", dotenv, DEFAULT_BASE_URL),
            "live_eval": str(_env("PATCHPILOT_LIVE_EVAL", dotenv, "")).lower() in {"1", "true", "yes"},
            "enable_prompt_cache": str(_env("PATCHPILOT_PROMPT_CACHE", dotenv, "1")).lower() not in {"0", "false", "no"},
        }
        int_envs = {
            "max_model_calls": "PATCHPILOT_MAX_MODEL_CALLS",
            "model_retry_attempts": "PATCHPILOT_MODEL_RETRY_ATTEMPTS",
            "model_rate_limit_calls": "PATCHPILOT_MODEL_RATE_LIMIT_CALLS",
            "model_rate_limit_period_seconds": "PATCHPILOT_MODEL_RATE_LIMIT_PERIOD_SECONDS",
        }
        for field_name, env_name in int_envs.items():
            if value := os.getenv(env_name):
                data[field_name] = int(value)
        if repo is not None:
            data["repo"] = repo
        data.update(overrides)
        if "model" in data:
            data["model"] = _resolve_minimax_model(str(data["model"]))
        if "model_profile" in overrides and "model" not in overrides:
            data["model"] = resolve_model_profile(str(overrides["model_profile"]), None, dotenv)
        return cls(**data)


def resolve_model_profile(profile: str, explicit_model: str | None = None, dotenv: dict[str, str] | None = None) -> str:
    """Resolve model profiles while keeping v2 defaults constrained to MiniMax."""
    if explicit_model:
        return _resolve_minimax_model(explicit_model)
    dotenv = dotenv or {}
    if profile == "v2-strong":
        return _resolve_minimax_model(os.getenv("PATCHPILOT_V2_MODEL") or dotenv.get("PATCHPILOT_V2_MODEL"))
    if profile in MODEL_PROFILES:
        return MODEL_PROFILES[profile]
    return _resolve_minimax_model(profile)


def _resolve_minimax_model(model: str | None) -> str:
    if model and model.startswith(MINIMAX_MODEL_PREFIX):
        return model
    return DEFAULT_V2_MODEL


def _env(name: str, dotenv: dict[str, str], default: str | None) -> str | None:
    return os.getenv(name) or dotenv.get(name) or default


def _read_dotenv(repo: Path | None) -> dict[str, str]:
    candidates = [Path.cwd() / ".env"]
    if repo is not None:
        candidates.append(repo / ".env")
    values: dict[str, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values
