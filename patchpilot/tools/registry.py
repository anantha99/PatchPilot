"""Typed tool registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
import warnings

from pydantic import BaseModel
from pydantic.json_schema import PydanticJsonSchemaWarning

from patchpilot.errors import ToolError
from patchpilot.schemas.common import Permission, ToolNamespace


class RetryPolicy(BaseModel):
    attempts: int = 1
    multiplier: float = 0.25
    max_wait: float = 2.0


class RateLimitPolicy(BaseModel):
    calls: int = 60
    period_seconds: int = 60


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    namespace: ToolNamespace
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: Callable[[BaseModel, "ToolContext"], Awaitable[BaseModel]]
    permission: Permission
    retry_policy: RetryPolicy
    rate_limit: RateLimitPolicy

    def metadata(self, *, include_policy: bool = True, include_json_schema: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "namespace": self.namespace.value,
            "description": self.description,
            "permission": self.permission.value,
            "input_schema": self.input_schema.__name__,
            "output_schema": self.output_schema.__name__,
        }
        if include_json_schema:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", PydanticJsonSchemaWarning)
                data["input_json_schema"] = self.input_schema.model_json_schema()
                data["output_json_schema"] = self.output_schema.model_json_schema()
        if include_policy:
            data["retry_policy"] = self.retry_policy.model_dump()
            data["rate_limit"] = self.rate_limit.model_dump()
        return data


@dataclass(slots=True)
class ToolContext:
    repo_root: Any
    config: Any
    trace_store: Any | None = None
    session_id: str = "local"
    trace_id: str = "local"
    artifacts: dict[str, Any] | None = None
    command_history: list[Any] | None = None

    def __post_init__(self) -> None:
        if self.artifacts is None:
            self.artifacts = {}
        if self.command_history is None:
            self.command_history = []


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ToolError(f"Duplicate tool name: {spec.name}")
        expected_prefix = f"{spec.namespace.value}."
        if not spec.name.startswith(expected_prefix):
            raise ToolError(
                f"Tool {spec.name} must start with namespace prefix {expected_prefix}"
            )
        self._tools[spec.name] = spec

    def tool(
        self,
        *,
        name: str,
        namespace: ToolNamespace,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        permission: Permission,
        retry_policy: RetryPolicy | None = None,
        rate_limit: RateLimitPolicy | None = None,
    ) -> Callable[
        [Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]],
        Callable[[BaseModel, ToolContext], Awaitable[BaseModel]],
    ]:
        def decorator(
            handler: Callable[[BaseModel, ToolContext], Awaitable[BaseModel]],
        ) -> Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]:
            self.register(
                ToolSpec(
                    name=name,
                    namespace=namespace,
                    description=description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    handler=handler,
                    permission=permission,
                    retry_policy=retry_policy or RetryPolicy(),
                    rate_limit=rate_limit or RateLimitPolicy(),
                )
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    def list(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda item: item.name)

    def namespaces(self) -> set[str]:
        return {tool.namespace.value for tool in self._tools.values()}

    def by_namespace(self, namespace: ToolNamespace) -> list[ToolSpec]:
        return [tool for tool in self.list() if tool.namespace == namespace]

    def phase_view(self, allowed_names: set[str]) -> "ToolRegistry":
        view = ToolRegistry()
        for name in allowed_names:
            view.register(self.get(name))
        return view
