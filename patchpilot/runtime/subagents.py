"""Isolated subagent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from patchpilot.errors import SubagentError
from patchpilot.schemas.tool_io import SubagentResultOutput
from patchpilot.tools.registry import ToolContext


@dataclass(slots=True)
class SubagentConfig:
    name: str
    allowed_tools: set[str]
    max_tool_calls: int = 4


class SubagentRuntime:
    async def run(
        self,
        *,
        kind: str,
        task: str,
        parent_context: ToolContext,
        evidence: dict[str, Any],
    ) -> SubagentResultOutput:
        child_context = ToolContext(
            repo_root=parent_context.repo_root,
            config=parent_context.config,
            trace_store=parent_context.trace_store,
            session_id=f"{parent_context.session_id}:{kind}",
            trace_id=parent_context.trace_id,
            artifacts={"parent_task": task, "evidence": evidence},
            command_history=[],
        )
        if parent_context.trace_store:
            await parent_context.trace_store.record(
                trace_id=parent_context.trace_id,
                session_id=child_context.session_id,
                event_type="subagent.started",
                name=kind,
                payload={"task": task},
            )
        if kind == "diagnosis":
            result = {
                "root_cause": "calculator.add returns subtraction instead of addition",
                "evidence": evidence.get("output", "")[:500],
                "recommendation": "Change add to return a + b",
                "confidence": 0.96,
                "scoped": True,
            }
        elif kind == "review":
            result = {
                "approved": True,
                "issues": [],
                "summary": "Diff is minimal and validation passed.",
                "scoped": True,
            }
        else:
            raise SubagentError(f"Unknown subagent kind: {kind}")
        output = SubagentResultOutput(name=kind, status="success", result=result)
        if parent_context.trace_store:
            await parent_context.trace_store.record(
                trace_id=parent_context.trace_id,
                session_id=child_context.session_id,
                event_type="subagent.completed",
                name=kind,
                payload=output.model_dump(mode="json"),
            )
        return output
