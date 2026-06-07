"""OpenRouter HTTP response helpers for offline tests."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import Any

import httpx


class QueuedOpenRouterTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: Iterable[dict[str, Any] | Callable[[httpx.Request], dict[str, Any]]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            item = self._responses.pop(0)
            content = item(request) if callable(item) else item
        else:
            content = finish_selection()
        return httpx.Response(200, json=_completion(content), request=request)


class SchemaAwareOpenRouterTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *,
        tool_selections: Iterable[dict[str, Any] | Callable[[httpx.Request], dict[str, Any]]] = (),
        structured: dict[str, Iterable[dict[str, Any] | Callable[[httpx.Request], dict[str, Any]]]] | None = None,
    ) -> None:
        self._tool_selections = list(tool_selections)
        self._structured = {key: list(value) for key, value in (structured or {}).items()}
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        schema_name = _schema_name(request)
        if schema_name:
            queue = self._structured.get(schema_name) or []
            if not queue:
                raise AssertionError(f"No mocked OpenRouter structured response for {schema_name}")
            item = queue.pop(0)
        elif self._tool_selections:
            item = self._tool_selections.pop(0)
        else:
            item = finish_selection()
        content = item(request) if callable(item) else item
        return httpx.Response(200, json=_completion(content), request=request)


def tool_selection(
    *,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
    rationale: str = "test selection",
    finish: bool = False,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "arguments": arguments or {},
        "rationale": rationale,
        "finish": finish,
    }


def finish_selection(rationale: str = "let workflow guardrails continue") -> dict[str, Any]:
    return tool_selection(finish=True, rationale=rationale)


def _completion(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "test-openrouter",
        "model": "minimax/minimax-m3",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps(content)},
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


def _schema_name(request: httpx.Request) -> str | None:
    payload = json.loads(request.content.decode("utf-8"))
    system = ((payload.get("messages") or [{}])[0] or {}).get("content") or ""
    match = re.search(r"matching the ([A-Za-z0-9_]+) schema", system)
    return match.group(1) if match else None
