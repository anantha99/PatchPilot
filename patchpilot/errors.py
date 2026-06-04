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


class MissingModelApiKeyError(ModelError):
    """A live model provider was selected without required credentials."""


class ModelRequestError(ModelError):
    """The model provider request failed."""


class ModelResponseError(ModelError):
    """The model provider returned an unsupported or invalid response."""


class ModelSchemaError(ModelResponseError):
    """The model response did not match PatchPilot's structured schema."""


class ModelBudgetError(ModelError):
    """The configured model-call budget was exhausted."""


class RateLimitError(PatchPilotError):
    """A configured rate limit prevented execution."""


class SubagentError(PatchPilotError):
    """A subagent failed or returned an invalid result."""


class ExecutionTimeoutError(ToolError):
    """A local command exceeded its timeout."""


class PolicyError(ToolError):
    """A tool call violated a permission or execution policy."""
