"""Tool execution with validation, policy checks, retries, and traces."""

from __future__ import annotations

import time
from typing import Any

from aiolimiter import AsyncLimiter
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from patchpilot.errors import PolicyError, ToolError, ToolValidationError
from patchpilot.schemas.common import Permission
from patchpilot.tools.registry import ToolContext, ToolRegistry, ToolSpec


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._limiters: dict[str, AsyncLimiter] = {}

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | BaseModel,
        context: ToolContext,
    ) -> BaseModel:
        spec = self.registry.get(tool_name)
        self._check_permission(spec, context)
        model_input = self._validate_input(spec, arguments)
        limiter = self._limiter_for(spec)
        start = time.perf_counter()
        await self._trace(context, "tool.started", spec.name, "success", {"input": model_input.model_dump(mode="json")})
        try:
            async with limiter:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(spec.retry_policy.attempts),
                    wait=wait_exponential(
                        multiplier=spec.retry_policy.multiplier,
                        max=spec.retry_policy.max_wait,
                    ),
                    retry=retry_if_exception_type(ToolError),
                    reraise=True,
                ):
                    with attempt:
                        raw = await spec.handler(model_input, context)
            output = self._validate_output(spec, raw)
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self._trace(context, "tool.completed", spec.name, "success", {"duration_ms": duration_ms}, duration_ms)
            return output
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self._trace(
                context,
                "tool.completed",
                spec.name,
                "failed",
                {"duration_ms": duration_ms, "error": str(exc), "error_type": type(exc).__name__},
                duration_ms,
            )
            raise

    def _validate_input(self, spec: ToolSpec, arguments: dict[str, Any] | BaseModel) -> BaseModel:
        if isinstance(arguments, BaseModel):
            arguments = arguments.model_dump()
        try:
            return spec.input_schema.model_validate(arguments)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Invalid input for {spec.name}", {"errors": exc.errors()}
            ) from exc

    def _validate_output(self, spec: ToolSpec, output: BaseModel) -> BaseModel:
        try:
            return spec.output_schema.model_validate(output)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Invalid output for {spec.name}", {"errors": exc.errors()}
            ) from exc

    def _check_permission(self, spec: ToolSpec, context: ToolContext) -> None:
        config = context.config
        if spec.permission == Permission.WRITE and not config.allow_write:
            raise PolicyError(f"{spec.name} requires --allow-write")
        if spec.permission == Permission.EXEC and not config.allow_exec:
            raise PolicyError(f"{spec.name} requires --allow-exec")

    def _limiter_for(self, spec: ToolSpec) -> AsyncLimiter:
        policy = spec.rate_limit
        key = spec.name
        if key not in self._limiters:
            self._limiters[key] = AsyncLimiter(policy.calls, policy.period_seconds)
        return self._limiters[key]

    async def _trace(
        self,
        context: ToolContext,
        event_type: str,
        name: str,
        status: str,
        payload: dict[str, Any],
        duration_ms: int = 0,
    ) -> None:
        if context.trace_store is not None:
            await context.trace_store.record(
                trace_id=context.trace_id,
                session_id=context.session_id,
                event_type=event_type,
                name=name,
                status=status,
                payload=payload,
                duration_ms=duration_ms,
            )
