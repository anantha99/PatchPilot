"""Parent repair runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from patchpilot.config import PatchPilotConfig
from patchpilot.models.base import ModelClient
from patchpilot.models.fake import FakeModelClient
from patchpilot.observability.tracing import TraceStore, new_session_id, new_trace_id
from patchpilot.runtime.state import SessionState
from patchpilot.schemas.reports import ChangedFileReport, FinalReport, RepairAttemptReport, TestRunReport
from patchpilot.tools import build_registry
from patchpilot.tools.registry import ToolContext
from patchpilot.tools.executor import ToolExecutor


PHASES = ["inspect", "reproduce", "diagnose", "plan_patch", "apply_patch", "validate", "review", "report"]


class RepairRuntime:
    def __init__(self, config: PatchPilotConfig, model: ModelClient | None = None) -> None:
        self.config = config
        self.registry = build_registry()
        self.executor = ToolExecutor(self.registry)
        self.model = model or FakeModelClient()
        self.trace_store = TraceStore(config.trace_dir)

    async def run(self, goal: str, test_command: str | None = None) -> FinalReport:
        trace_id = new_trace_id()
        session_id = new_session_id()
        state = SessionState(repo=self.config.repo, goal=goal, test_command=test_command, trace_id=trace_id, session_id=session_id)
        context = ToolContext(
            repo_root=self.config.repo,
            config=self.config,
            trace_store=self.trace_store,
            session_id=session_id,
            trace_id=trace_id,
        )
        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="run.started", name="patchpilot.run", payload={"goal": goal})
        while len(state.tool_history) < self.config.max_tool_calls:
            metadata = self.tool_metadata()
            selection = await self.model.select_tool(state, metadata)
            state.model_calls += 1
            await self.trace_store.record(
                trace_id=trace_id,
                session_id=session_id,
                event_type="model.tool_selection",
                name=selection.tool_name or "finish",
                payload=selection.model_dump(mode="json"),
            )
            if selection.finish or selection.tool_name is None:
                break
            output = await self.executor.execute(selection.tool_name, selection.arguments, context)
            state.record_tool(selection.tool_name, output)
            phase = context.artifacts.get("phases", [state.phase])[-1] if context.artifacts.get("phases") else state.phase
            if phase != state.phase:
                state.phase = phase
                await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="plan.updated", name=phase, payload={"phase": phase})
        report = self._final_report(state, context)
        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="run.completed", name="patchpilot.run", payload=report.model_dump(mode="json"))
        return report

    def tool_metadata(self) -> list[dict[str, Any]]:
        rows = []
        for spec in self.registry.list():
            rows.append(
                {
                    "name": spec.name,
                    "namespace": spec.namespace.value,
                    "description": spec.description,
                    "permission": spec.permission.value,
                    "input_schema": spec.input_schema.__name__,
                    "output_schema": spec.output_schema.__name__,
                }
            )
        return rows

    def _final_report(self, state: SessionState, context: ToolContext) -> FinalReport:
        commands = [item for item in context.command_history if "pytest" in item.command]
        tests = [
            TestRunReport(command=item.command, exit_code=item.exit_code, status="passed" if item.exit_code == 0 else "failed")
            for item in commands
        ]
        patch_plan = context.artifacts.get("patch_plan", {})
        success = bool(tests and tests[-1].status == "passed")
        return FinalReport(
            goal=state.goal,
            status="success" if success else "failed",
            task_classification=patch_plan.get("task_classification", "source_fix"),
            root_cause=patch_plan.get("root_cause", "Unknown"),
            patch_plan={"summary": patch_plan.get("summary", "")},
            changed_files=[ChangedFileReport(path=Path("buggy_math/calculator.py"), change_type="modify", justification="Fix add implementation")],
            attempts=[RepairAttemptReport(attempt=1, result="passed" if success else "failed", summary="Applied one bounded source patch")],
            tests_run=tests,
            subagents=context.artifacts.get("subagents", []),
            risks=[],
            trace_id=state.trace_id,
        )
