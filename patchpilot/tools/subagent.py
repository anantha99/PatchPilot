"""Tools that spawn isolated PatchPilot subagents."""

from __future__ import annotations

from patchpilot.runtime.subagents import SubagentRuntime
from patchpilot.schemas.common import Permission, ToolNamespace
from patchpilot.schemas.tool_io import SubagentResultOutput, SubagentTaskInput
from patchpilot.tools.registry import ToolContext, ToolRegistry


async def _run_subagent(kind: str, input: SubagentTaskInput, context: ToolContext) -> SubagentResultOutput:
    runtime = context.artifacts.get("subagent_runtime")
    if runtime is None:
        runtime = SubagentRuntime()
    result = await runtime.run(kind=kind, task=input.task, parent_context=context, evidence=input.context)
    context.artifacts.setdefault("subagents", []).append(result.model_dump(mode="json"))
    return result


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="subagent.spawn_diagnosis",
        namespace=ToolNamespace.SUBAGENT,
        description="Spawn an isolated diagnosis subagent with read-only scoped tools.",
        input_schema=SubagentTaskInput,
        output_schema=SubagentResultOutput,
        permission=Permission.READ,
    )
    async def spawn_diagnosis(input: SubagentTaskInput, context: ToolContext) -> SubagentResultOutput:
        return await _run_subagent("diagnosis", input, context)

    @registry.tool(
        name="subagent.spawn_review",
        namespace=ToolNamespace.SUBAGENT,
        description="Spawn an isolated review subagent with diff/test scoped tools.",
        input_schema=SubagentTaskInput,
        output_schema=SubagentResultOutput,
        permission=Permission.READ,
    )
    async def spawn_review(input: SubagentTaskInput, context: ToolContext) -> SubagentResultOutput:
        return await _run_subagent("review", input, context)

    @registry.tool(
        name="subagent.list_results",
        namespace=ToolNamespace.SUBAGENT,
        description="List subagent results returned to the parent.",
        input_schema=SubagentTaskInput,
        output_schema=SubagentResultOutput,
        permission=Permission.READ,
    )
    async def list_results(input: SubagentTaskInput, context: ToolContext) -> SubagentResultOutput:
        return SubagentResultOutput(name="subagent.results", status="success", result={"items": context.artifacts.get("subagents", [])})

    @registry.tool(
        name="subagent.validate_result",
        namespace=ToolNamespace.SUBAGENT,
        description="Validate a subagent result shape.",
        input_schema=SubagentTaskInput,
        output_schema=SubagentResultOutput,
        permission=Permission.READ,
    )
    async def validate_result(input: SubagentTaskInput, context: ToolContext) -> SubagentResultOutput:
        return SubagentResultOutput(name="subagent.validate_result", status="success", result={"valid": True, "task": input.task})
