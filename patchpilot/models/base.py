"""Model client contracts for structured tool selection."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None


class ModelCacheMetadata(BaseModel):
    cache_hit: bool | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ModelCallMetadata(BaseModel):
    provider: str
    model: str
    provider_request_id: str | None = None
    finish_reason: str | None = None
    duration_ms: int = 0
    retry_count: int = 0
    usage: ModelUsage = Field(default_factory=ModelUsage)
    cache: ModelCacheMetadata = Field(default_factory=ModelCacheMetadata)


class ModelJsonResponse(BaseModel):
    data: dict[str, Any]
    metadata: ModelCallMetadata | None = None


class ToolSelection(BaseModel):
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    finish: bool = False
    metadata: ModelCallMetadata | None = None


class ModelClient:
    provider: str = "unknown"

    async def select_tool(self, state: Any, tools: list[dict[str, Any]]) -> ToolSelection:
        raise NotImplementedError

    async def complete_json(
        self,
        *,
        prompt: dict[str, Any],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> ModelJsonResponse:
        raise NotImplementedError
