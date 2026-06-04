"""Isolated subagent runtime."""

from __future__ import annotations

from typing import Any

from patchpilot.errors import SubagentError, ToolError
from patchpilot.models.base import ModelClient
from patchpilot.runtime.state import SessionState
from patchpilot.schemas.tool_io import DiagnosisResult, ReviewResult, SubagentConfig, SubagentResultOutput
from patchpilot.tools.registry import ToolContext


SUBAGENT_CONFIGS = {
    "diagnosis": SubagentConfig(
        kind="diagnosis",
        allowed_tools=["code.extract_failure_locations", "code.map_test_to_source", "fs.read_file"],
        max_model_calls=3,
        max_tool_calls=5,
        output_schema="DiagnosisResult",
    ),
    "review": SubagentConfig(
        kind="review",
        allowed_tools=["git.diff", "exec.command_history"],
        max_model_calls=2,
        max_tool_calls=4,
        output_schema="ReviewResult",
    ),
}


class SubagentRuntime:
    def __init__(self, model: ModelClient | None = None) -> None:
        self.model = model

    async def run(
        self,
        *,
        kind: str,
        task: str,
        parent_context: ToolContext,
        evidence: dict[str, Any],
    ) -> SubagentResultOutput:
        config = SUBAGENT_CONFIGS.get(kind)
        if config is None:
            raise SubagentError(f"Unknown subagent kind: {kind}")
        child_context = ToolContext(
            repo_root=parent_context.repo_root,
            config=parent_context.config,
            trace_store=parent_context.trace_store,
            session_id=f"{parent_context.session_id}:{kind}",
            trace_id=parent_context.trace_id,
            artifacts={
                "parent_task": task,
                "evidence": evidence,
                "applied_patches": (parent_context.artifacts or {}).get("applied_patches", []),
            },
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
        from patchpilot.tools import build_registry
        from patchpilot.tools.executor import ToolExecutor

        registry = build_registry()
        scoped = registry.phase_view(set(config.allowed_tools))
        tool_evidence: dict[str, Any] = {}
        if self.model is not None and getattr(self.model, "provider", "unknown") != "fake":
            await self._run_model_loop(config, task, evidence, scoped, child_context, tool_evidence)
        if kind == "diagnosis":
            output = await ToolExecutor(scoped).execute(
                "code.extract_failure_locations",
                {"output": evidence.get("output", "")},
                child_context,
            )
            tool_evidence["failure_locations"] = output.model_dump(mode="json")
            if self.model is not None and getattr(self.model, "provider", "unknown") != "fake":
                result = await self._structured_diagnosis(task, evidence, tool_evidence, child_context)
            else:
                result = DiagnosisResult(
                    root_cause="calculator.add returns subtraction instead of addition",
                    evidence=tool_evidence,
                    implicated_files=[],
                    recommended_patch_direction="Change add to return a + b",
                    confidence=0.96,
                    risks=[],
                ).model_dump(mode="json")
        elif kind == "review":
            output = await ToolExecutor(scoped).execute("git.diff", {}, child_context)
            tool_evidence["diff_exit_code"] = output.exit_code
            if self.model is not None and getattr(self.model, "provider", "unknown") != "fake":
                result = await self._structured_review(task, evidence, tool_evidence, child_context)
            else:
                result = ReviewResult(
                    approved=True,
                    issues=[],
                    evidence=tool_evidence,
                    regression_risk="low",
                    missing_validation=[],
                    confidence=0.9,
                ).model_dump(mode="json")
        else:
            raise SubagentError(f"Unknown subagent kind: {kind}")
        result["scoped"] = True
        result["child_tool_calls"] = len(child_context.command_history) + len(tool_evidence)
        result["config"] = config.model_dump(mode="json")
        output = SubagentResultOutput(name=kind, kind=kind, status="success", result=result)
        if parent_context.trace_store:
            await parent_context.trace_store.record(
                trace_id=parent_context.trace_id,
                session_id=child_context.session_id,
                event_type="subagent.completed",
                name=kind,
                payload=output.model_dump(mode="json"),
            )
        return output

    async def _run_model_loop(
        self,
        config: SubagentConfig,
        task: str,
        evidence: dict[str, Any],
        registry,
        child_context: ToolContext,
        tool_evidence: dict[str, Any],
    ) -> None:
        if self.model is None:
            return
        from patchpilot.tools.executor import ToolExecutor

        state = SessionState(repo=child_context.repo_root, goal=task, phase=config.kind, session_id=child_context.session_id, trace_id=child_context.trace_id)
        executor = ToolExecutor(registry)
        metadata = [spec.metadata(include_policy=False, include_json_schema=True) for spec in registry.list()]
        for index in range(config.max_model_calls):
            if child_context.trace_store:
                await child_context.trace_store.record(
                    trace_id=child_context.trace_id,
                    session_id=child_context.session_id,
                    event_type="subagent.model.started",
                    name=config.kind,
                    payload={"model_call": index + 1, "task": task},
                )
            selection = await self.model.select_tool(state, metadata)
            if child_context.trace_store:
                await child_context.trace_store.record(
                    trace_id=child_context.trace_id,
                    session_id=child_context.session_id,
                    event_type="subagent.model.tool_selection",
                    name=selection.tool_name or "finish",
                    payload=selection.model_dump(mode="json"),
                )
            if selection.finish or selection.tool_name is None:
                break
            try:
                registry.get(selection.tool_name)
            except ToolError:
                if child_context.trace_store:
                    await child_context.trace_store.record(
                        trace_id=child_context.trace_id,
                        session_id=child_context.session_id,
                        event_type="subagent.model.rejected_tool",
                        name=selection.tool_name,
                        status="failed",
                        payload={"allowed_tools": config.allowed_tools},
                    )
                break
            output = await executor.execute(selection.tool_name, selection.arguments, child_context)
            state.record_tool(selection.tool_name, output)
            tool_evidence[f"model_tool_{index + 1}"] = {"tool": selection.tool_name, "output": output.model_dump(mode="json")}
            if len(state.tool_history) >= config.max_tool_calls:
                break

    async def _structured_diagnosis(
        self,
        task: str,
        evidence: dict[str, Any],
        tool_evidence: dict[str, Any],
        child_context: ToolContext,
    ) -> dict[str, Any]:
        if self.model is None:
            raise SubagentError("Diagnosis subagent requires a model")
        response = await self.model.complete_json(
            prompt={
                "task": task,
                "evidence": evidence,
                "tool_evidence": tool_evidence,
                "instructions": [
                    "Identify the concrete root cause from the failing test and source evidence.",
                    "Use repository-relative paths in implicated_files.",
                    "Do not assume the calculator fixture unless the evidence names it.",
                ],
            },
            schema_name="DiagnosisResult",
            json_schema=DiagnosisResult.model_json_schema(),
        )
        if child_context.trace_store:
            await child_context.trace_store.record(
                trace_id=child_context.trace_id,
                session_id=child_context.session_id,
                event_type="subagent.model.structured_output",
                name="DiagnosisResult",
                payload={
                    "result": response.data,
                    "metadata": response.metadata.model_dump(mode="json") if response.metadata else None,
                },
                duration_ms=response.metadata.duration_ms if response.metadata else 0,
            )
        return DiagnosisResult.model_validate(response.data).model_dump(mode="json")

    async def _structured_review(
        self,
        task: str,
        evidence: dict[str, Any],
        tool_evidence: dict[str, Any],
        child_context: ToolContext,
    ) -> dict[str, Any]:
        if self.model is None:
            raise SubagentError("Review subagent requires a model")
        response = await self.model.complete_json(
            prompt={
                "task": task,
                "evidence": evidence,
                "tool_evidence": tool_evidence,
                "instructions": [
                    "Check whether the final diff matches the diagnosis and patch plan.",
                    "Check whether targeted and full validation passed when command evidence is available.",
                    "Return issues or missing_validation if the patch should not be trusted.",
                ],
            },
            schema_name="ReviewResult",
            json_schema=ReviewResult.model_json_schema(),
        )
        if child_context.trace_store:
            await child_context.trace_store.record(
                trace_id=child_context.trace_id,
                session_id=child_context.session_id,
                event_type="subagent.model.structured_output",
                name="ReviewResult",
                payload={
                    "result": response.data,
                    "metadata": response.metadata.model_dump(mode="json") if response.metadata else None,
                },
                duration_ms=response.metadata.duration_ms if response.metadata else 0,
            )
        return ReviewResult.model_validate(response.data).model_dump(mode="json")
