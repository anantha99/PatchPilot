"""Model client contracts for structured tool selection."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSelection(BaseModel):
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    finish: bool = False


class ModelClient:
    async def select_tool(self, state: Any, tools: list[dict[str, Any]]) -> ToolSelection:
        raise NotImplementedError
