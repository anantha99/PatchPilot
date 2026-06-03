"""Typed errors used throughout PatchPilot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PatchPilotError(Exception):
    """Base error for all PatchPilot failures."""

    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


class ToolError(PatchPilotError):
    """A tool failed while executing."""


class ToolValidationError(ToolError):
    """A tool input or output failed schema validation."""


class ModelError(PatchPilotError):
    """A model provider call failed."""


class RateLimitError(PatchPilotError):
    """A configured rate limit prevented execution."""


class SubagentError(PatchPilotError):
    """A subagent failed or returned an invalid result."""


class ExecutionTimeoutError(ToolError):
    """A local command exceeded its timeout."""


class PolicyError(ToolError):
    """A tool call violated a permission or execution policy."""

