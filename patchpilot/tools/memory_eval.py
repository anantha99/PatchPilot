"""In-session memory and eval support tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from patchpilot.evals.checks import trace_tool_checks
from patchpilot.errors import ToolValidationError
from patchpilot.schemas.common import EmptyInput, JsonObject, Permission, TextOutput, ToolNamespace
from patchpilot.schemas.tool_io import (
    ArtifactInput,
    ArtifactKeyInput,
    ArtifactsOutput,
    ContextSummaryInput,
    ContextSummaryOutput,
    DecisionInput,
    DecisionOutput,
    EvalScoreOutput,
    FixtureInput,
    ObservationInput,
    ObservationOutput,
    PhaseInput,
    PatchPlan,
    RetrieveArtifactsInput,
    TraceAssertInput,
)
from patchpilot.tools.registry import ToolContext, ToolRegistry


def _bucket(context: ToolContext, key: str) -> list:
    context.artifacts.setdefault(key, [])
    return context.artifacts[key]


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="memory_eval.record_observation",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Record a structured observation in session memory.",
        input_schema=ObservationInput,
        output_schema=ObservationOutput,
        permission=Permission.READ,
    )
    async def record_observation(input: ObservationInput, context: ToolContext) -> ObservationOutput:
        observation_id = f"obs_{uuid4().hex[:8]}"
        _bucket(context, "observations").append({"id": observation_id, **input.model_dump()})
        return ObservationOutput(observation_id=observation_id)

    @registry.tool(
        name="memory_eval.summarize_context",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Summarize recent observations for compact model context.",
        input_schema=ContextSummaryInput,
        output_schema=ContextSummaryOutput,
        permission=Permission.READ,
    )
    async def summarize_context(input: ContextSummaryInput, context: ToolContext) -> ContextSummaryOutput:
        text = "\n".join(input.observations)
        return ContextSummaryOutput(summary=text[: input.max_chars])

    @registry.tool(
        name="memory_eval.retrieve_artifacts",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Retrieve selected or all session artifacts.",
        input_schema=RetrieveArtifactsInput,
        output_schema=ArtifactsOutput,
        permission=Permission.READ,
    )
    async def retrieve_artifacts(input: RetrieveArtifactsInput, context: ToolContext) -> ArtifactsOutput:
        if input.keys is None:
            return ArtifactsOutput(artifacts=context.artifacts)
        return ArtifactsOutput(artifacts={key: context.artifacts.get(key) for key in input.keys})

    @registry.tool(
        name="memory_eval.record_decision",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Record a runtime decision and reason.",
        input_schema=DecisionInput,
        output_schema=DecisionOutput,
        permission=Permission.READ,
    )
    async def record_decision(input: DecisionInput, context: ToolContext) -> DecisionOutput:
        decision_id = f"dec_{uuid4().hex[:8]}"
        _bucket(context, "decisions").append({"id": decision_id, **input.model_dump()})
        return DecisionOutput(decision_id=decision_id)

    @registry.tool(
        name="memory_eval.store_artifact",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Store a named JSON-serializable artifact.",
        input_schema=ArtifactInput,
        output_schema=JsonObject,
        permission=Permission.READ,
    )
    async def store_artifact(input: ArtifactInput, context: ToolContext) -> JsonObject:
        value = input.value
        if input.key == "patch_plan":
            try:
                value = PatchPlan.model_validate(value).model_dump(mode="json")
            except Exception as exc:
                raise ToolValidationError("Invalid patch_plan artifact", {"error": str(exc)}) from exc
        context.artifacts[input.key] = value
        return JsonObject(data={"key": input.key, "stored": True})

    @registry.tool(
        name="memory_eval.load_artifact",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Load a named artifact from session memory.",
        input_schema=ArtifactKeyInput,
        output_schema=JsonObject,
        permission=Permission.READ,
    )
    async def load_artifact(input: ArtifactKeyInput, context: ToolContext) -> JsonObject:
        return JsonObject(data={"key": input.key, "value": context.artifacts.get(input.key)})

    @registry.tool(
        name="memory_eval.mark_phase",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Record the current runtime phase.",
        input_schema=PhaseInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def mark_phase(input: PhaseInput, context: ToolContext) -> TextOutput:
        _bucket(context, "phases").append(input.phase)
        return TextOutput(text=input.phase)

    @registry.tool(
        name="memory_eval.load_fixture_metadata",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Load metadata for a known eval fixture.",
        input_schema=FixtureInput,
        output_schema=JsonObject,
        permission=Permission.READ,
    )
    async def load_fixture_metadata(input: FixtureInput, context: ToolContext) -> JsonObject:
        fixture_root = Path(context.repo_root)
        return JsonObject(data={"fixture": input.fixture, "root": str(fixture_root), "expected_changed_file": "buggy_math/calculator.py"})

    @registry.tool(
        name="memory_eval.assert_trace_properties",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Assert basic assignment properties from the current trace.",
        input_schema=TraceAssertInput,
        output_schema=EvalScoreOutput,
        permission=Permission.READ,
    )
    async def assert_trace_properties(input: TraceAssertInput, context: ToolContext) -> EvalScoreOutput:
        events = context.trace_store.read(input.trace_id) if context.trace_store else []
        checks = trace_tool_checks(events, min_tool_calls=input.min_tool_calls)
        return EvalScoreOutput(passed=all(checks.values()), score=sum(checks.values()) / len(checks), checks=checks)

    @registry.tool(
        name="memory_eval.export_session",
        namespace=ToolNamespace.MEMORY_EVAL,
        description="Export session memory as a JSON object.",
        input_schema=EmptyInput,
        output_schema=JsonObject,
        permission=Permission.READ,
    )
    async def export_session(input: EmptyInput, context: ToolContext) -> JsonObject:
        return JsonObject(data={"artifacts": _json_safe(context.artifacts), "commands": [cmd.model_dump(mode="json") for cmd in context.command_history]})


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_runtime"):
                continue
            safe[str(key)] = _json_safe(item)
        return safe
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return repr(value)
