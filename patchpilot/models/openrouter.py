"""OpenRouter model client behind the model contract."""

from __future__ import annotations

import json
import time
from typing import Any

from aiolimiter import AsyncLimiter
import httpx
from pydantic import ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import MissingModelApiKeyError, ModelRequestError, ModelResponseError, ModelSchemaError
from patchpilot.models.base import ModelCacheMetadata, ModelCallMetadata, ModelClient, ModelJsonResponse, ModelUsage, ToolSelection
from patchpilot.runtime.prompts import structured_json_prompt, tool_selection_prompt


class OpenRouterModelClient(ModelClient):
    provider = "openrouter"

    def __init__(self, config: PatchPilotConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport
        self._limiter = AsyncLimiter(config.model_rate_limit_calls, config.model_rate_limit_period_seconds)

    async def select_tool(self, state, tools) -> ToolSelection:
        if not self.config.openrouter_api_key:
            raise MissingModelApiKeyError("OPENROUTER_API_KEY is required for live model runs")
        prompt = tool_selection_prompt(state, _compact_tools(tools))
        started = time.perf_counter()
        retry_count = 0
        async with self._client() as client:
            async with self._limiter:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self.config.model_retry_attempts),
                    wait=wait_exponential(
                        multiplier=self.config.model_retry_multiplier,
                        max=self.config.model_retry_max_wait,
                    ),
                    retry=retry_if_exception_type((httpx.HTTPError, ModelRequestError, ModelResponseError)),
                    reraise=True,
                ):
                    with attempt:
                        retry_count = attempt.retry_state.attempt_number - 1
                        response = await client.post(
                            "/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.config.openrouter_api_key}",
                                "HTTP-Referer": "https://github.com/patchpilot/patchpilot",
                                "X-Title": "PatchPilot",
                            },
                            json=self._request_body(prompt),
                        )
                        if response.status_code >= 400:
                            raise ModelRequestError(
                                "OpenRouter call failed",
                                {"status_code": response.status_code, "body": response.text[:1000]},
                            )
                        duration_ms = int((time.perf_counter() - started) * 1000)
                        return self._selection_from_response(response, duration_ms=duration_ms, retry_count=retry_count)
        raise ModelResponseError("OpenRouter did not return a tool selection")

    async def complete_json(
        self,
        *,
        prompt: dict[str, Any],
        schema_name: str,
        json_schema: dict[str, Any],
    ) -> ModelJsonResponse:
        if not self.config.openrouter_api_key:
            raise MissingModelApiKeyError("OPENROUTER_API_KEY is required for live model runs")
        started = time.perf_counter()
        retry_count = 0
        async with self._client() as client:
            async with self._limiter:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self.config.model_retry_attempts),
                    wait=wait_exponential(
                        multiplier=self.config.model_retry_multiplier,
                        max=self.config.model_retry_max_wait,
                    ),
                    retry=retry_if_exception_type((httpx.HTTPError, ModelRequestError, ModelResponseError)),
                    reraise=True,
                ):
                    with attempt:
                        retry_count = attempt.retry_state.attempt_number - 1
                        response = await client.post(
                            "/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.config.openrouter_api_key}",
                                "HTTP-Referer": "https://github.com/patchpilot/patchpilot",
                                "X-Title": "PatchPilot",
                            },
                            json=self._request_body(structured_json_prompt(schema_name=schema_name, json_schema=json_schema, task=prompt)),
                        )
                        if response.status_code >= 400:
                            raise ModelRequestError(
                                "OpenRouter structured JSON call failed",
                                {"status_code": response.status_code, "body": response.text[:1000]},
                            )
                        duration_ms = int((time.perf_counter() - started) * 1000)
                        data, metadata = self._json_from_response(response, duration_ms=duration_ms, retry_count=retry_count)
                        return ModelJsonResponse(data=data, metadata=metadata)
        raise ModelResponseError("OpenRouter did not return structured JSON")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.config.base_url, timeout=30, transport=self._transport)

    def _request_body(self, prompt: dict[str, Any]) -> dict[str, Any]:
        stable = prompt.get("stable") or {}
        role = stable.get("role")
        if role == "structured-json":
            instructions = " ".join(str(item) for item in stable.get("instructions", []))
            system_content = instructions or "Return only JSON matching the supplied schema."
        else:
            system_content = (
                "You are PatchPilot's tool-selection model. Return only JSON matching this shape: "
                "{\"tool_name\": string|null, \"arguments\": object, \"rationale\": string, \"finish\": boolean}."
            )
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_content,
                },
                {"role": "user", "content": json.dumps(prompt, default=str)},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.config.enable_prompt_cache:
            body["provider"] = {"require_parameters": False}
        return body

    def _json_from_response(
        self,
        response: httpx.Response,
        *,
        duration_ms: int,
        retry_count: int,
    ) -> tuple[dict[str, Any], ModelCallMetadata]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ModelResponseError("OpenRouter returned invalid JSON", {"body": response.text[:1000]}) from exc
        try:
            choice = payload["choices"][0]
            message = choice["message"]
            content = message.get("content")
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelResponseError("OpenRouter response is missing chat completion fields", {"payload": payload}) from exc
        if finish_reason not in {None, "stop", "tool_calls"}:
            raise ModelResponseError("OpenRouter returned unsupported finish state", {"finish_reason": finish_reason})
        if content is None:
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                content = ((tool_calls[0].get("function") or {}).get("arguments"))
        if content is None and isinstance(message.get("reasoning"), str):
            reasoning = message["reasoning"].strip()
            if reasoning.startswith("{") and reasoning.endswith("}"):
                content = reasoning
        if content is None:
            raise ModelResponseError("OpenRouter returned empty message content", {"id": payload.get("id"), "finish_reason": finish_reason})
        try:
            data = _json_content(content)
        except json.JSONDecodeError as exc:
            raise ModelSchemaError("OpenRouter structured response was not JSON", {"content": content}) from exc
        metadata = ModelCallMetadata(
            provider=self.provider,
            model=str(payload.get("model") or self.config.model),
            provider_request_id=payload.get("id"),
            finish_reason=finish_reason,
            duration_ms=duration_ms,
            retry_count=retry_count,
            usage=self._usage(payload.get("usage") or {}),
            cache=self._cache(payload.get("usage") or {}),
        )
        return data, metadata

    def _selection_from_response(self, response: httpx.Response, *, duration_ms: int, retry_count: int) -> ToolSelection:
        data, metadata = self._json_from_response(response, duration_ms=duration_ms, retry_count=retry_count)
        try:
            selection = ToolSelection.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise ModelSchemaError("OpenRouter tool selection did not match schema", {"content": data}) from exc
        selection.metadata = metadata
        return selection

    def _usage(self, usage: dict[str, Any]) -> ModelUsage:
        return ModelUsage(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            estimated_cost=_float_or_none(usage.get("cost") or usage.get("estimated_cost")),
        )

    def _cache(self, usage: dict[str, Any]) -> ModelCacheMetadata:
        details = usage.get("prompt_tokens_details") or {}
        read_tokens = usage.get("cache_read_tokens") or details.get("cached_tokens")
        write_tokens = usage.get("cache_write_tokens")
        return ModelCacheMetadata(
            cache_hit=bool(read_tokens) if read_tokens is not None else None,
            cache_read_tokens=read_tokens,
            cache_write_tokens=write_tokens,
            raw={key: value for key, value in usage.items() if "cache" in key.lower()},
        )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise json.JSONDecodeError("content is not a JSON string", str(content), 0)
    text = content.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("content is not a JSON object", text, 0)
    return data


def _extract_json_object(text: str) -> str:
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _compact_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for tool in tools:
        schema = tool.get("input_json_schema") or {}
        properties = schema.get("properties") or {}
        fields = {
            name: {
                key: value
                for key, value in {
                    "type": spec.get("type"),
                    "default": spec.get("default"),
                    "description": spec.get("description"),
                }.items()
                if value is not None
            }
            for name, spec in properties.items()
        }
        compact.append(
            {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "input_schema": tool.get("input_schema"),
                "required": schema.get("required") or [],
                "fields": fields,
            }
        )
    return compact
