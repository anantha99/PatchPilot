"""Parent repair runtime."""

from __future__ import annotations

import re
import json
import time
from pathlib import Path
from typing import Any, Callable

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import ModelBudgetError, PolicyError, ToolError
from patchpilot.models.base import ModelClient, ToolSelection
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.observability.tracing import TraceStore, new_session_id, new_trace_id
from patchpilot.runtime.context import compact_state
from patchpilot.runtime.state import EvidenceLink, RepairAttemptArtifact, SessionState
from patchpilot.schemas.reports import ChangedFileReport, FinalReport, RepairAttemptReport, TestRunReport
from patchpilot.schemas.tool_io import PatchPlan
from patchpilot.tools import build_registry
from patchpilot.tools.helpers import iter_repo_files
from patchpilot.tools.registry import ToolContext
from patchpilot.tools.executor import ToolExecutor


PHASES = ["inspect", "reproduce", "diagnose", "plan_patch", "apply_patch", "validate", "review", "report"]
PHASE_MARK_TOOL = "session.mark_phase"
LEGACY_PHASE_MARK_TOOL = "memory_eval.mark_phase"
PHASE_TOOLS = {
    "inspect": {
        PHASE_MARK_TOOL,
        "fs.list_dir",
        "code.detect_language",
        "code.detect_package_manager",
        "code.find_tests",
        "exec.detect_test_command",
    },
    "reproduce": {PHASE_MARK_TOOL, "exec.run_tests"},
    "diagnose": {
        PHASE_MARK_TOOL,
        "code.extract_failure_locations",
        "subagent.spawn_diagnosis",
        "session.record_observation",
    },
    "plan_patch": {
        PHASE_MARK_TOOL,
        "code.map_test_to_source",
        "fs.read_file",
        "session.store_artifact",
        "code.validate_patch_shape",
        "session.record_decision",
    },
    "apply_patch": {PHASE_MARK_TOOL, "fs.apply_patch"},
    "validate": {PHASE_MARK_TOOL, "exec.run_targeted_tests", "exec.run_tests", "git.diff"},
    "review": {
        PHASE_MARK_TOOL,
        "subagent.spawn_review",
        "session.summarize_context",
        "session.retrieve_artifacts",
    },
    "report": {PHASE_MARK_TOOL, "exec.command_history", "session.export_session"},
}
TOOL_ALIASES = {
    "code.detect_test_command": "exec.detect_test_command",
    "code.run_tests": "exec.run_tests",
    "code.run_targeted_tests": "exec.run_targeted_tests",
    "code.read_file": "fs.read_file",
    "code.read_source": "fs.read_file",
    "code.read_test": "fs.read_file",
    "fs.glob_files": "fs.glob",
    "memory.mark_phase": PHASE_MARK_TOOL,
    "memory_eval.mark_phase": PHASE_MARK_TOOL,
    "memory_eval.record_observation": "session.record_observation",
    "memory_eval.summarize_context": "session.summarize_context",
    "memory_eval.retrieve_artifacts": "session.retrieve_artifacts",
    "memory_eval.record_decision": "session.record_decision",
    "memory_eval.store_artifact": "session.store_artifact",
    "memory_eval.load_artifact": "session.load_artifact",
    "memory_eval.assert_trace_properties": "session.assert_trace_properties",
    "memory_eval.export_session": "session.export_session",
}


class RepairRuntime:
    def __init__(
        self,
        config: PatchPilotConfig,
        model: ModelClient | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.registry = build_registry()
        self.model = model or OpenRouterModelClient(config)
        self.trace_store = TraceStore(config.trace_dir)
        self.progress = progress
        self._phase_registries = {
            phase: self.registry.phase_view(allowed_tools)
            for phase, allowed_tools in PHASE_TOOLS.items()
        }
        self._phase_executors = {
            phase: ToolExecutor(registry)
            for phase, registry in self._phase_registries.items()
        }
        self._phase_metadata = {
            phase: [spec.metadata(include_policy=False, include_json_schema=True) for spec in registry.list()]
            for phase, registry in self._phase_registries.items()
        }

    async def run(self, goal: str, test_command: str | None = None) -> FinalReport:
        trace_id = new_trace_id()
        session_id = new_session_id()
        started_at = time.monotonic()
        state = SessionState(repo=self.config.repo, goal=goal, test_command=test_command, trace_id=trace_id, session_id=session_id)
        context = ToolContext(
            repo_root=self.config.repo,
            config=self.config,
            trace_store=self.trace_store,
            session_id=session_id,
            trace_id=trace_id,
        )
        from patchpilot.runtime.subagents import SubagentRuntime

        context.artifacts["subagent_runtime"] = SubagentRuntime(model=self.model)
        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="run.started", name="patchpilot.run", payload={"goal": goal})
        self._progress(
            event="run_started",
            trace_id=trace_id,
            phase=state.phase,
            model_calls=state.model_calls,
            tool_calls=len(state.tool_history),
            retry_count=max(0, state.attempt - 1),
            elapsed_seconds=0.0,
        )
        try:
            while len(state.tool_history) < self.config.max_tool_calls and state.model_calls < self.config.max_model_calls:
                self._progress(
                    event="phase",
                    trace_id=trace_id,
                    phase=state.phase,
                    model_calls=state.model_calls,
                    tool_calls=len(state.tool_history),
                    retry_count=max(0, state.attempt - 1),
                    elapsed_seconds=round(time.monotonic() - started_at, 1),
                )
                await self.trace_store.record(
                    trace_id=trace_id,
                    session_id=session_id,
                    event_type="model.started",
                    name=getattr(self.model, "provider", "unknown"),
                    payload={"phase": state.phase, "model_call": state.model_calls + 1},
                )
                try:
                    selection = await self.model.select_tool(state, self.tool_metadata(state.phase))
                except Exception as exc:
                    await self.trace_store.record(
                        trace_id=trace_id,
                        session_id=session_id,
                        event_type="model.failed",
                        name=getattr(self.model, "provider", "unknown"),
                        status="failed",
                        payload={"phase": state.phase, "error_type": type(exc).__name__, "error": str(exc)},
                    )
                    raise
                state.model_calls += 1
                if selection.metadata is not None:
                    state.model_metadata.append(selection.metadata.model_dump(mode="json"))
                await self.trace_store.record(
                    trace_id=trace_id,
                    session_id=session_id,
                    event_type="model.completed",
                    name=selection.tool_name or "finish",
                    payload={
                        "phase": state.phase,
                        "metadata": selection.metadata.model_dump(mode="json") if selection.metadata else None,
                    },
                    duration_ms=selection.metadata.duration_ms if selection.metadata else 0,
                )
                await self.trace_store.record(
                    trace_id=trace_id,
                    session_id=session_id,
                    event_type="model.tool_selection",
                    name=selection.tool_name or "finish",
                    payload=selection.model_dump(mode="json"),
                )
                if selection.finish or selection.tool_name is None:
                    fallback = self._scaffolded_selection(state, context, reason="model_finished_before_report")
                    if fallback is None:
                        state.termination_reason = "model_finished"
                        break
                    selection = fallback
                    await self.trace_store.record(
                        trace_id=trace_id,
                        session_id=session_id,
                        event_type="runtime.scaffolded_tool_selection",
                        name=selection.tool_name or "finish",
                        payload=selection.model_dump(mode="json"),
                    )
                selection = await self._normalize_selection(selection, state, context)
                selection.arguments = self._prepare_arguments(selection.tool_name, selection.arguments, context)
                output = await self._phase_executor(state.phase).execute(selection.tool_name, selection.arguments, context)
                state.record_tool(selection.tool_name, output)
                self._progress(
                    event="tool_completed",
                    trace_id=trace_id,
                    phase=state.phase,
                    tool=selection.tool_name,
                    model_calls=state.model_calls,
                    tool_calls=len(state.tool_history),
                    retry_count=max(0, state.attempt - 1),
                    elapsed_seconds=round(time.monotonic() - started_at, 1),
                )
                _update_working_set(state, selection.tool_name, output)
                if await self._maybe_handle_apply_failure(state, context, selection.tool_name, output):
                    continue
                if await self._maybe_handle_validation_failure(state, context, selection.tool_name, output):
                    continue
                if selection.tool_name == PHASE_MARK_TOOL:
                    phase = output.text
                    if phase != state.phase:
                        if phase not in PHASES:
                            raise ToolError(f"Invalid phase transition: {phase}")
                        state.phase = phase
                        self._progress(
                            event="phase_changed",
                            trace_id=trace_id,
                            phase=phase,
                            model_calls=state.model_calls,
                            tool_calls=len(state.tool_history),
                            retry_count=max(0, state.attempt - 1),
                            elapsed_seconds=round(time.monotonic() - started_at, 1),
                        )
                        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="plan.updated", name=phase, payload={"phase": phase})
                await self._maybe_create_patch_plan(state, context)
                if len(state.tool_history) and len(state.tool_history) % 10 == 0:
                    compacted = compact_state(state)
                    context.artifacts["compact_state"] = compacted
                    await self.trace_store.record(
                        trace_id=trace_id,
                        session_id=session_id,
                        event_type="context.compacted",
                        name=state.phase,
                        payload=compacted,
                    )
            if state.model_calls >= self.config.max_model_calls and state.termination_reason is None:
                state.termination_reason = "budget_exhausted"
                raise ModelBudgetError("Model-call budget exhausted", {"max_model_calls": self.config.max_model_calls})
        except Exception as exc:
            context.artifacts["runtime_error"] = {"type": type(exc).__name__, "message": str(exc)}
            state.termination_reason = state.termination_reason or "failed"
            await self.trace_store.record(
                trace_id=trace_id,
                session_id=session_id,
                event_type="run.failed",
                name="patchpilot.run",
                status="failed",
                payload=context.artifacts["runtime_error"],
            )
        report = self._final_report(state, context)
        report.report_path = self._write_report(report)
        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="run.completed", name="patchpilot.run", payload=report.model_dump(mode="json"))
        self._progress(
            event="run_completed",
            trace_id=trace_id,
            phase=state.phase,
            status=report.status,
            report_path=report.report_path,
            model_calls=state.model_calls,
            tool_calls=len(state.tool_history),
            retry_count=max(0, len(report.attempts) - 1),
            elapsed_seconds=round(time.monotonic() - started_at, 1),
        )
        return report

    def _progress(self, **payload: Any) -> None:
        if self.progress is None:
            return
        try:
            self.progress(payload)
        except OSError:
            return

    def tool_metadata(self, phase: str = "inspect") -> list[dict[str, Any]]:
        return [row.copy() for row in self._phase_metadata.get(phase, self._phase_metadata["inspect"])]

    def _phase_executor(self, phase: str):
        return self._phase_executors.get(phase, self._phase_executors["inspect"])

    def _write_report(self, report: FinalReport) -> str:
        report_dir = self.trace_store.trace_dir.parent / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"{report.trace_id}.json"
        report.report_path = str(path)
        path.write_text(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
        return str(path)

    async def _maybe_handle_validation_failure(
        self,
        state: SessionState,
        context: ToolContext,
        tool_name: str,
        output: Any,
    ) -> bool:
        if state.phase != "validate" or tool_name not in {"exec.run_targeted_tests", "exec.run_tests"}:
            return False
        data = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        if not isinstance(data, dict) or data.get("exit_code") == 0:
            return False
        if not context.artifacts.get("applied_patches"):
            return False
        failure_category = "targeted_tests_failed" if tool_name == "exec.run_targeted_tests" else "full_tests_failed"
        attempt = self._build_attempt(
            state,
            context,
            status="failed",
            failure_category=failure_category,
            retry_rationale="Validation failed after an applied patch; gather updated evidence and request a revised patch plan.",
        )
        state.attempts.append(attempt)
        context.artifacts["attempts"] = [item.model_dump(mode="json") for item in state.attempts]
        state.previous_patch_failures.append(attempt.model_dump(mode="json"))
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="runtime.repair_attempt",
            name=f"attempt_{attempt.attempt}",
            status="failed",
            payload=attempt.model_dump(mode="json"),
        )
        if state.attempt >= self.config.max_repair_attempts:
            state.termination_reason = "budget_exhausted"
            state.phase = "report"
            state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "report"}})
            await self.trace_store.record(
                trace_id=state.trace_id,
                session_id=state.session_id,
                event_type="plan.updated",
                name="report",
                payload={"phase": "report", "reason": "max repair attempts exhausted"},
            )
            return True
        state.attempt += 1
        state.validation_status = "retry_pending"
        context.artifacts.pop("patch_plan", None)
        context.artifacts.pop("patch_validation", None)
        state.phase = "diagnose"
        state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "diagnose"}})
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="runtime.retry_scheduled",
            name=f"attempt_{state.attempt}",
            payload={"next_attempt": state.attempt, "failure_category": failure_category},
        )
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="plan.updated",
            name="diagnose",
            payload={"phase": "diagnose", "reason": "validation failure retry"},
        )
        return True

    async def _maybe_handle_apply_failure(
        self,
        state: SessionState,
        context: ToolContext,
        tool_name: str,
        output: Any,
    ) -> bool:
        if state.phase != "apply_patch" or tool_name != "fs.apply_patch":
            return False
        data = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        if not isinstance(data, dict) or data.get("applied") is not False:
            return False
        attempt = self._build_attempt(
            state,
            context,
            status="failed",
            failure_category="patch_did_not_apply",
            retry_rationale="Patch application failed; read the implicated source files again and request a revised patch plan.",
        )
        state.attempts.append(attempt)
        context.artifacts["attempts"] = [item.model_dump(mode="json") for item in state.attempts]
        state.previous_patch_failures.append(attempt.model_dump(mode="json"))
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="runtime.repair_attempt",
            name=f"attempt_{attempt.attempt}",
            status="failed",
            payload=attempt.model_dump(mode="json"),
        )
        context.artifacts.pop("patch_plan", None)
        context.artifacts.pop("patch_validation", None)
        if state.attempt >= self.config.max_repair_attempts:
            state.termination_reason = "budget_exhausted"
            state.phase = "report"
            state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "report"}})
            await self.trace_store.record(
                trace_id=state.trace_id,
                session_id=state.session_id,
                event_type="plan.updated",
                name="report",
                payload={"phase": "report", "reason": "max repair attempts exhausted after apply failure"},
            )
            return True
        state.attempt += 1
        state.validation_status = "retry_pending"
        state.phase = "plan_patch"
        state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "plan_patch"}})
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="runtime.retry_scheduled",
            name=f"attempt_{state.attempt}",
            payload={"next_attempt": state.attempt, "failure_category": "patch_did_not_apply"},
        )
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="plan.updated",
            name="plan_patch",
            payload={"phase": "plan_patch", "reason": "patch application failure retry"},
        )
        return True

    def _build_attempt(
        self,
        state: SessionState,
        context: ToolContext,
        *,
        status: str,
        failure_category: str | None = None,
        retry_rationale: str | None = None,
        review_output: dict[str, Any] | None = None,
    ) -> RepairAttemptArtifact:
        patch_plan = context.artifacts.get("patch_plan") or {}
        validation = context.artifacts.get("patch_validation") or {}
        apply_result = _latest_tool_output_after_marker(state, "fs.apply_patch", "apply_patch")
        targeted = _latest_tool_output_after_marker(state, "exec.run_targeted_tests", "validate")
        full = _latest_tool_output_after_marker(state, "exec.run_tests", "validate")
        diff = _latest_tool_output_after_marker(state, "git.diff", "validate")
        changed_files = [Path(path) for path in apply_result.get("changed_files", [])]
        if not changed_files:
            changed_files = _paths_from_diff(str(diff.get("stdout") or ""))
        return RepairAttemptArtifact(
            attempt=state.attempt,
            status=status,
            patch_plan=patch_plan,
            semantic_validation=validation,
            apply_result=apply_result,
            targeted_test=targeted,
            full_test=full,
            diff_summary=str(diff.get("stdout") or "")[:4000],
            review_output=review_output or {},
            changed_files=changed_files,
            failure_category=failure_category,
            retry_rationale=retry_rationale,
        )

    def _final_report(self, state: SessionState, context: ToolContext) -> FinalReport:
        tests = [
            TestRunReport(command=item.command, exit_code=item.exit_code, status="passed" if item.exit_code == 0 else "failed")
            for item in context.command_history
        ]
        patch_plan = context.artifacts.get("patch_plan", {})
        runtime_error = context.artifacts.get("runtime_error")
        review_result = _latest_review_result(context)
        review_rejected = review_result.get("approved") is False
        success = bool(
            tests
            and tests[-1].status == "passed"
            and runtime_error is None
            and state.termination_reason != "budget_exhausted"
            and not review_rejected
        )
        model_summary = self._model_summary(state)
        changed_files = self._changed_files(state, patch_plan)
        attempt_artifacts = list(state.attempts)
        if context.artifacts.get("applied_patches") and not any(attempt.attempt == state.attempt for attempt in attempt_artifacts):
            attempt_artifacts.append(
                self._build_attempt(
                    state,
                    context,
                    status="passed" if success else "failed",
                    failure_category=None if success else _failure_category(state, runtime_error, review_rejected),
                    review_output=review_result,
                )
            )
        attempts = [
            RepairAttemptReport(
                attempt=attempt.attempt,
                result="passed" if attempt.status == "passed" else ("budget_exhausted" if attempt.status == "budget_exhausted" else "failed"),
                summary=str((attempt.patch_plan or {}).get("summary") or attempt.failure_category or "Repair attempt"),
                changed_files=attempt.changed_files,
                semantic_validation=attempt.semantic_validation,
                targeted_test=attempt.targeted_test,
                full_test=attempt.full_test,
                failure_category=attempt.failure_category,
                retry_rationale=attempt.retry_rationale,
            )
            for attempt in attempt_artifacts
        ]
        semantic_validation = []
        if context.artifacts.get("patch_validation"):
            semantic_validation.append(context.artifacts["patch_validation"])
        semantic_validation.extend(item.get("validation", {}) for item in context.artifacts.get("rejected_patch_plans", []))
        return FinalReport(
            goal=state.goal,
            status="success" if success else ("partial" if tests and any(test.status == "passed" for test in tests) and runtime_error is None else "failed"),
            task_classification=patch_plan.get("task_classification", "source_fix"),
            root_cause=patch_plan.get("root_cause") or _diagnosis_root_cause(context) or (runtime_error["message"] if runtime_error else "Unknown"),
            patch_plan=_report_patch_plan(patch_plan),
            changed_files=changed_files,
            attempts=attempts or [RepairAttemptReport(attempt=1, result="passed" if success else "failed", summary=patch_plan.get("summary", "Run validation commands"))],
            tests_run=tests,
            subagents=context.artifacts.get("subagents", []),
            risks=[],
            trace_id=state.trace_id,
            tool_calls=len(state.tool_history),
            model_provider=model_summary["provider"],
            model=model_summary["model"],
            model_usage_summary=model_summary["usage"],
            estimated_cost=model_summary["estimated_cost"],
            cache_summary=model_summary["cache"],
            semantic_validation=semantic_validation,
            rejected_patch_plans=context.artifacts.get("rejected_patch_plans", []),
            retry_summary={
                "attempt_count": len(attempts) or 1,
                "max_repair_attempts": self.config.max_repair_attempts,
                "termination_reason": state.termination_reason,
            },
            review_result=review_result,
            trace_path=str(self.trace_store.trace_dir / f"{state.trace_id}.jsonl"),
            failure_reason=runtime_error["message"] if runtime_error else (_failure_category(state, runtime_error, review_rejected) if not success else None),
        )

    def _prepare_arguments(self, tool_name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if tool_name == "subagent.spawn_diagnosis":
            subagent_context = dict(arguments.get("context") or {})
            subagent_context.setdefault("source_file_hints", _source_file_hints(Path(context.repo_root)))
            return {**arguments, "context": subagent_context}
        if tool_name == "code.validate_patch_shape":
            patch_plan = context.artifacts.get("patch_plan") or {}
            if patch_plan:
                return {
                    **arguments,
                    "patch": arguments.get("patch") or patch_plan.get("patch") or patch_plan.get("unified_diff") or "",
                    "structured_edits": arguments.get("structured_edits") or patch_plan.get("edits", []),
                    "evidence_refs": arguments.get("evidence_refs") or patch_plan.get("evidence_refs", []),
                    "root_cause": arguments.get("root_cause") or patch_plan.get("root_cause", ""),
                    "patch_plan": patch_plan,
                }
            return arguments
        if tool_name != "fs.apply_patch":
            return arguments
        patch_plan = context.artifacts.get("patch_plan") or {}
        patch = patch_plan.get("patch") or patch_plan.get("unified_diff") or ""
        structured_edits = patch_plan.get("edits", [])
        if not patch and not structured_edits:
            raise PolicyError("fs.apply_patch requires a validated patch_plan patch or structured edits")
        validation = context.artifacts.get("patch_validation")
        if not validation or not validation.get("valid"):
            raise PolicyError("fs.apply_patch requires valid patch validation before write")
        return {**arguments, "patch": patch, "structured_edits": structured_edits}

    def _scaffolded_selection(self, state: SessionState, context: ToolContext, *, reason: str) -> ToolSelection | None:
        if state.phase == "report":
            return None
        if state.validation_status == "passed" and not self.config.allow_write:
            return None
        next_tool = _next_phase_tool(state, context)
        if next_tool is None:
            return None
        tool_name, arguments = next_tool
        return ToolSelection(
            tool_name=tool_name,
            arguments=arguments,
            rationale=f"Runtime scaffold continued required phase workflow after {reason}.",
        )

    async def _normalize_selection(self, selection: ToolSelection, state: SessionState, context: ToolContext) -> ToolSelection:
        if selection.tool_name is None:
            return selection
        raw_tool_name = selection.tool_name
        normalized_tool_name = TOOL_ALIASES.get(raw_tool_name, raw_tool_name)
        if normalized_tool_name != raw_tool_name:
            selection = selection.model_copy(update={"tool_name": normalized_tool_name})
            await self.trace_store.record(
                trace_id=state.trace_id,
                session_id=state.session_id,
                event_type="runtime.normalized_tool_selection",
                name=normalized_tool_name,
                payload={"from": raw_tool_name, "to": normalized_tool_name, "phase": state.phase},
            )
        if self._tool_allowed(state.phase, selection.tool_name):
            if (
                state.phase == "plan_patch"
                and selection.tool_name == "session.store_artifact"
                and selection.arguments.get("key") == "patch_plan"
                and getattr(self.model, "provider", "unknown") != "fake"
            ):
                return await self._scaffold_invalid_selection(
                    selection,
                    state,
                    context,
                    reason="patch_plan_requires_typed_model_json",
                )
            if (
                state.phase == "plan_patch"
                and selection.tool_name == "code.validate_patch_shape"
                and not context.artifacts.get("patch_plan")
            ):
                return await self._scaffold_invalid_selection(
                    selection,
                    state,
                    context,
                    reason="patch_validation_requires_typed_patch_plan",
                )
            return selection
        return await self._scaffold_invalid_selection(selection, state, context, reason=f"invalid_tool:{selection.tool_name}")

    async def _scaffold_invalid_selection(
        self,
        selection: ToolSelection,
        state: SessionState,
        context: ToolContext,
        *,
        reason: str,
    ) -> ToolSelection:
        fallback = self._scaffolded_selection(state, context, reason=reason)
        if fallback is None:
            raise ToolError(f"Tool {selection.tool_name} is not available in phase {state.phase}")
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="runtime.scaffolded_tool_selection",
            name=fallback.tool_name or "finish",
            payload=fallback.model_dump(mode="json"),
        )
        return fallback

    def _tool_allowed(self, phase: str, tool_name: str) -> bool:
        try:
            self._phase_registries.get(phase, self._phase_registries["inspect"]).get(tool_name)
            return True
        except ToolError:
            return False

    async def _maybe_create_patch_plan(self, state: SessionState, context: ToolContext) -> None:
        if state.phase != "plan_patch":
            return
        if getattr(self.model, "provider", "unknown") == "fake":
            return
        if context.artifacts.get("patch_plan"):
            return
        files = _read_files_from_history(state.tool_history)
        if not _has_patch_plan_evidence(files, context, state):
            return
        while state.model_calls < self.config.max_model_calls:
            response = await self.model.complete_json(
                prompt={
                    "goal": state.goal,
                    "test_command": state.test_command,
                    "failure_output": state.last_command_output,
                    "recent_tool_history": state.tool_history[-10:],
                    "subagents": context.artifacts.get("subagents", []),
                    "files": files,
                    "rejected_patch_plans": context.artifacts.get("rejected_patch_plans", [])[-3:],
                    "requirements": _patch_plan_requirements(),
                },
                schema_name="PatchPlan",
                json_schema=PatchPlan.model_json_schema(),
            )
            state.model_calls += 1
            if response.metadata is not None:
                state.model_metadata.append(response.metadata.model_dump(mode="json"))
            patch_plan = PatchPlan.model_validate(response.data)
            context.artifacts["patch_plan"] = patch_plan.model_dump(mode="json")
            await self.trace_store.record(
                trace_id=state.trace_id,
                session_id=state.session_id,
                event_type="model.patch_plan",
                name="PatchPlan",
                payload={
                    "patch_plan": patch_plan.model_dump(mode="json"),
                    "metadata": response.metadata.model_dump(mode="json") if response.metadata else None,
                },
                duration_ms=response.metadata.duration_ms if response.metadata else 0,
            )
            state.tool_history.append({"tool_name": "model.patch_plan", "output": patch_plan.model_dump(mode="json")})
            validation = await self._phase_executor("plan_patch").execute(
                "code.validate_patch_shape",
                {
                    "task_classification": patch_plan.task_classification,
                    "target_files": _validation_target_files(patch_plan),
                    "patch": patch_plan.patch or patch_plan.unified_diff or "",
                    "structured_edits": [edit.model_dump(mode="json") for edit in patch_plan.edits],
                    "evidence_refs": patch_plan.evidence_refs,
                    "root_cause": patch_plan.root_cause,
                    "patch_plan": patch_plan.model_dump(mode="json"),
                    "max_diff_lines": self.config.max_diff_lines,
                },
                context,
            )
            state.record_tool("code.validate_patch_shape", validation)
            if validation.valid:
                state.phase = "apply_patch"
                state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "apply_patch"}})
                await self.trace_store.record(
                    trace_id=state.trace_id,
                    session_id=state.session_id,
                    event_type="plan.updated",
                    name="apply_patch",
                    payload={"phase": "apply_patch", "reason": "validated model patch plan"},
                )
                return
            rejected = {"patch_plan": patch_plan.model_dump(mode="json"), "validation": validation.model_dump(mode="json")}
            state.rejected_patch_plans.append(rejected)
            rejected_plans = context.artifacts.setdefault("rejected_patch_plans", [])
            if not rejected_plans or rejected_plans[-1] != rejected:
                rejected_plans.append(rejected)
            context.artifacts.pop("patch_plan", None)
            context.artifacts.pop("patch_validation", None)
            await self.trace_store.record(
                trace_id=state.trace_id,
                session_id=state.session_id,
                event_type="runtime.patch_plan_rejected",
                name="code.validate_patch_shape",
                status="failed",
                payload=rejected,
            )
            if len(context.artifacts.get("rejected_patch_plans", [])) >= self.config.max_repair_attempts:
                state.termination_reason = "budget_exhausted"
                state.phase = "report"
                state.tool_history.append({"tool_name": PHASE_MARK_TOOL, "output": {"text": "report"}})
                await self.trace_store.record(
                    trace_id=state.trace_id,
                    session_id=state.session_id,
                    event_type="plan.updated",
                    name="report",
                    payload={"phase": "report", "reason": "max patch plan rejections exhausted"},
                )
                return

    def _changed_files(self, state: SessionState, patch_plan: dict[str, Any]) -> list[ChangedFileReport]:
        paths: list[Path] = []
        for item in state.tool_history:
            output = item.get("output") or {}
            if item.get("tool_name") == "fs.apply_patch":
                paths.extend(Path(path) for path in output.get("changed_files", []))
            if item.get("tool_name") == "git.diff" and output.get("stdout"):
                paths.extend(_paths_from_diff(output["stdout"]))
        if not paths:
            paths.extend(Path(edit["path"]) for edit in patch_plan.get("edits", []) if "path" in edit)
        seen: set[str] = set()
        reports: list[ChangedFileReport] = []
        for path in paths:
            key = path.as_posix()
            if key in seen:
                continue
            seen.add(key)
            reports.append(
                ChangedFileReport(
                    path=path,
                    change_type="modify",
                    justification="Derived from applied patch/diff artifacts",
                )
            )
        return reports

    def _model_summary(self, state: SessionState) -> dict[str, Any]:
        total_input = 0
        total_output = 0
        total_tokens = 0
        estimated_cost = 0.0
        saw_cost = False
        cache_read = 0
        cache_write = 0
        provider = getattr(self.model, "provider", self.config.model_provider)
        model = self.config.model
        for item in state.model_metadata:
            provider = item.get("provider") or provider
            model = item.get("model") or model
            usage = item.get("usage") or {}
            total_input += usage.get("input_tokens") or 0
            total_output += usage.get("output_tokens") or 0
            total_tokens += usage.get("total_tokens") or 0
            if usage.get("estimated_cost") is not None:
                saw_cost = True
                estimated_cost += usage["estimated_cost"]
            cache = item.get("cache") or {}
            cache_read += cache.get("cache_read_tokens") or 0
            cache_write += cache.get("cache_write_tokens") or 0
        return {
            "provider": provider,
            "model": model,
            "usage": {
                "input_tokens": total_input or None,
                "output_tokens": total_output or None,
                "total_tokens": total_tokens or None,
                "model_calls": state.model_calls,
            },
            "estimated_cost": estimated_cost if saw_cost else None,
            "cache": {
                "cache_read_tokens": cache_read or None,
                "cache_write_tokens": cache_write or None,
                "observed": bool(cache_read or cache_write),
            },
        }


def _paths_from_diff(diff: str) -> list[Path]:
    paths: list[Path] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            paths.append(Path(line.removeprefix("+++ b/")))
    return paths


def _source_file_hints(root: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(iter_repo_files(root)):
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root)
        if _is_test_path(rel.as_posix()):
            continue
        paths.append(rel.as_posix())
    return paths[:40]


def _latest_tool_output(state: SessionState, tool_name: str) -> dict[str, Any]:
    for item in reversed(state.tool_history):
        if item.get("tool_name") != tool_name:
            continue
        output = item.get("output")
        return output if isinstance(output, dict) else {}
    return {}


def _latest_tool_output_after_marker(state: SessionState, tool_name: str, phase: str) -> dict[str, Any]:
    start = 0
    for index in range(len(state.tool_history) - 1, -1, -1):
        item = state.tool_history[index]
        if _is_phase_marker(item) and (item.get("output") or {}).get("text") == phase:
            start = index + 1
            break
    for item in reversed(state.tool_history[start:]):
        if item.get("tool_name") != tool_name:
            continue
        output = item.get("output")
        return output if isinstance(output, dict) else {}
    return {}


def _is_phase_marker(item: dict[str, Any]) -> bool:
    return item.get("tool_name") in {PHASE_MARK_TOOL, LEGACY_PHASE_MARK_TOOL}


def _update_working_set(state: SessionState, tool_name: str, output: Any) -> None:
    data = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
    if not isinstance(data, dict):
        return
    if tool_name == "code.find_tests":
        for path in data.get("test_files", []):
            _append_path(state.working_set.relevant_tests, Path(path))
    elif tool_name == "code.extract_failure_locations":
        for location in data.get("locations", []):
            location_path = str(location).split(":", 1)[0]
            path = Path(location_path)
            if _is_test_path(path.as_posix()):
                _append_path(state.working_set.relevant_tests, path)
            elif path.suffix == ".py":
                _append_path(state.working_set.implicated_sources, path)
    elif tool_name == "code.map_test_to_source":
        candidates: list[Path] = []
        for result in data.get("results", []):
            file_path = str(result.get("file_path", ""))
            if file_path and not _is_test_path(file_path) and file_path.endswith(".py"):
                candidates.append(Path(file_path))
                _append_path(state.working_set.implicated_sources, Path(file_path))
        test_path = state.working_set.relevant_tests[-1].as_posix() if state.working_set.relevant_tests else "unknown"
        if candidates:
            state.working_set.source_candidates[test_path] = list(dict.fromkeys(candidates))
    elif tool_name == "fs.read_file":
        path = Path(str(data.get("path", "")))
        content = str(data.get("content", ""))
        if path.as_posix():
            if _is_test_path(path.as_posix()):
                _append_path(state.working_set.relevant_tests, path)
            elif path.suffix == ".py":
                _append_path(state.working_set.implicated_sources, path)
            state.working_set.summaries[path.as_posix()] = _summarize_text(content)
            state.working_set.evidence_links.append(EvidenceLink(source=tool_name, path=path, summary=_summarize_text(content, 240)))
    elif tool_name == "subagent.spawn_diagnosis":
        result = data.get("result") or {}
        for path in result.get("implicated_files") or []:
            _append_path(state.working_set.implicated_sources, Path(path))
        root_cause = result.get("root_cause")
        if root_cause:
            state.working_set.evidence_links.append(EvidenceLink(source="diagnosis", summary=str(root_cause)))
    elif tool_name == "code.validate_patch_shape":
        for path in data.get("changed_files") or data.get("target_files") or []:
            if not _is_test_path(str(path)):
                _append_path(state.working_set.implicated_sources, Path(path))


def _append_path(paths: list[Path], path: Path) -> None:
    normalized = Path(path.as_posix())
    if normalized not in paths:
        paths.append(normalized)


def _summarize_text(text: str, max_chars: int = 500) -> str:
    compact = " ".join(text.strip().split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _patch_plan_requirements() -> list[str]:
    requirements = [
        "Return minimal source-file edits only.",
        "Do not edit tests.",
        "Use edits[].before as the exact SEARCH text currently present in the file.",
        "Use edits[].after as the exact REPLACE text PatchPilot should write.",
        "Prefer leaving patch empty; PatchPilot will generate a clean diff from local file changes after applying structured edits.",
        "Use repository-relative paths.",
        "Infer every changed file from the failure output, read files, imports, and diagnosis evidence.",
        "Do not assume hidden expected files or fixture metadata; no fixture oracle is available during repair.",
    ]
    return requirements


def _validation_target_files(patch_plan: PatchPlan) -> list[str]:
    return [path.as_posix() for path in (patch_plan.planned_changed_files or [edit.path for edit in patch_plan.edits])]


def _report_patch_plan(patch_plan: dict[str, Any]) -> dict[str, Any]:
    edits = patch_plan.get("edits") or []
    return {
        "summary": patch_plan.get("summary", ""),
        "planned_changed_files": patch_plan.get("planned_changed_files", []),
        "edit_paths": [str(edit.get("path")) for edit in edits if isinstance(edit, dict) and edit.get("path")],
        "evidence_refs": patch_plan.get("evidence_refs", []),
        "validation_expectations": patch_plan.get("validation_expectations", []),
        "risk_notes": patch_plan.get("risk_notes", []),
        "edits": [
            {
                "path": edit.get("path"),
                "before": edit.get("before"),
                "after": edit.get("after"),
                "evidence_refs": edit.get("evidence_refs", []),
                "purpose": edit.get("purpose", ""),
                "expected_validation": edit.get("expected_validation", []),
                "root_cause_linkage": edit.get("root_cause_linkage", ""),
            }
            for edit in edits
            if isinstance(edit, dict)
        ],
    }


def _next_phase_tool(state: SessionState, context: ToolContext) -> tuple[str, dict[str, Any]] | None:
    used = _used_since_phase_start(state)
    if state.phase == "inspect":
        for tool_name, arguments in [
            ("fs.list_dir", {"path": "."}),
            ("code.detect_language", {"path": "."}),
            ("code.detect_package_manager", {"path": "."}),
            ("code.find_tests", {"path": "."}),
            ("exec.detect_test_command", {}),
        ]:
            if tool_name not in used:
                return tool_name, arguments
        return PHASE_MARK_TOOL, {"phase": "reproduce"}
    if state.phase == "reproduce":
        if "exec.run_tests" not in used:
            return "exec.run_tests", {"command": state.test_command} if state.test_command else {}
        return PHASE_MARK_TOOL, {"phase": "diagnose"}
    if state.phase == "diagnose":
        if "code.extract_failure_locations" not in used:
            return "code.extract_failure_locations", {"output": state.last_command_output}
        if "subagent.spawn_diagnosis" not in used:
            return "subagent.spawn_diagnosis", {
                "task": "Diagnose the reproduced failing test and identify the smallest source fix.",
                "context": {"test_output": state.last_command_output, "recent_tool_history": state.tool_history[-8:]},
            }
        if "session.record_observation" not in used:
            return "session.record_observation", {
                "text": _diagnosis_observation(context),
                "tags": ["diagnosis", "root_cause"],
            }
        return PHASE_MARK_TOOL, {"phase": "plan_patch"}
    if state.phase == "plan_patch":
        test_path = _first_test_path(state, context)
        if "code.map_test_to_source" not in used:
            return "code.map_test_to_source", {"path": test_path}
        source_path = _next_unread_source_path(state, context)
        if source_path and not _read_in_phase(state, source_path):
            return "fs.read_file", {"path": source_path}
        if test_path and not _read_in_phase(state, test_path):
            return "fs.read_file", {"path": test_path}
        return None
    if state.phase == "apply_patch":
        if "fs.apply_patch" not in used:
            return "fs.apply_patch", {}
        return PHASE_MARK_TOOL, {"phase": "validate"}
    if state.phase == "validate":
        if "exec.run_targeted_tests" not in used:
            target = _first_test_path(state, context)
            return "exec.run_targeted_tests", {"command": f"pytest {target}"} if target else {"command": state.test_command or "pytest"}
        if "exec.run_tests" not in used:
            return "exec.run_tests", {"command": state.test_command or "pytest"}
        if "git.diff" not in used:
            return "git.diff", {}
        return PHASE_MARK_TOOL, {"phase": "review"}
    if state.phase == "review":
        if "subagent.spawn_review" not in used:
            return "subagent.spawn_review", {
                "task": "Review the final patch against the diagnosis and validation evidence.",
                "context": {
                    "patch_plan": context.artifacts.get("patch_plan"),
                    "subagents": context.artifacts.get("subagents", []),
                    "recent_tool_history": state.tool_history[-8:],
                },
            }
        if "session.summarize_context" not in used:
            return "session.summarize_context", {
                "observations": _review_observations(context),
                "max_chars": 2000,
            }
        if "session.retrieve_artifacts" not in used:
            return "session.retrieve_artifacts", {"keys": ["patch_plan", "subagents", "phases"]}
        return PHASE_MARK_TOOL, {"phase": "report"}
    if state.phase == "report":
        if "exec.command_history" not in used:
            return "exec.command_history", {}
        if "session.export_session" not in used:
            return "session.export_session", {}
    return None


def _used_since_phase_start(state: SessionState) -> set[str]:
    return {item.get("tool_name", "") for item in state.tool_history[_phase_start_index(state) :]}


def _phase_start_index(state: SessionState) -> int:
    for index in range(len(state.tool_history) - 1, -1, -1):
        item = state.tool_history[index]
        if not _is_phase_marker(item):
            continue
        output = item.get("output") or {}
        if output.get("text") == state.phase:
            return index + 1
    return 0


def _read_in_phase(state: SessionState, path: str) -> bool:
    normalized = path.replace("\\", "/")
    for item in state.tool_history[_phase_start_index(state) :]:
        if item.get("tool_name") != "fs.read_file":
            continue
        output = item.get("output") or {}
        if str(output.get("path", "")).replace("\\", "/") == normalized:
            return True
    return False


def _first_test_path(state: SessionState, context: ToolContext) -> str:
    for location in re.findall(r"([A-Za-z0-9_./\\-]*tests[\\/][A-Za-z0-9_./\\-]+\.py):\d+", state.last_command_output):
        return location.replace("\\", "/")
    for item in reversed(state.tool_history):
        output = item.get("output") or {}
        paths = output.get("test_files") or []
        for path in paths:
            return str(path).replace("\\", "/")
    tests_dir = Path(context.repo_root) / "tests"
    if tests_dir.exists():
        for path in sorted(tests_dir.glob("test_*.py")):
            return path.relative_to(context.repo_root).as_posix()
    return "tests/test_pricing.py"


def _source_candidate(state: SessionState, context: ToolContext) -> str | None:
    for item in reversed(state.tool_history):
        if item.get("tool_name") != "code.map_test_to_source":
            continue
        for result in (item.get("output") or {}).get("results", []):
            path = str(result.get("file_path", "")).replace("\\", "/")
            if path and not _is_test_path(path) and path.endswith(".py"):
                return path
    test_path = _first_test_path(state, context)
    stem = Path(test_path).stem.removeprefix("test_")
    for path in sorted(iter_repo_files(Path(context.repo_root))):
        if path.name != f"{stem}.py":
            continue
        rel = path.relative_to(context.repo_root).as_posix()
        if not _is_test_path(rel):
            return rel
    return None


def _next_unread_source_path(state: SessionState, context: ToolContext) -> str | None:
    candidates: list[str] = []
    for path in state.working_set.implicated_sources:
        candidates.append(path.as_posix())
    for paths in state.working_set.source_candidates.values():
        for path in paths:
            candidates.append(path.as_posix())
    source_path = _source_candidate(state, context)
    if source_path:
        candidates.append(source_path)
    seen: set[str] = set()
    for path in candidates:
        normalized = path.replace("\\", "/")
        if normalized in seen or _is_test_path(normalized) or not normalized.endswith(".py"):
            continue
        seen.add(normalized)
        if _read_in_phase(state, normalized):
            continue
        if (Path(context.repo_root) / normalized).exists():
            return normalized
    return None


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return "/tests/" in f"/{normalized}" or Path(normalized).name.startswith("test_")


def _diagnosis_observation(context: ToolContext) -> str:
    subagents = context.artifacts.get("subagents", [])
    if subagents:
        result = subagents[-1].get("result", {})
        root_cause = result.get("root_cause")
        if root_cause:
            return str(root_cause)
    return "Diagnosis subagent completed."


def _review_observations(context: ToolContext) -> list[str]:
    observations = [str(item.get("text", "")) for item in context.artifacts.get("observations", []) if item.get("text")]
    for subagent in context.artifacts.get("subagents", []):
        result = subagent.get("result", {})
        if result.get("root_cause"):
            observations.append(str(result["root_cause"]))
        if result.get("approved") is not None:
            observations.append(f"review approved: {result['approved']}")
    return observations or ["Patch and validation artifacts are available for final review."]


def _latest_review_result(context: ToolContext) -> dict[str, Any]:
    for subagent in reversed(context.artifacts.get("subagents", [])):
        result = subagent.get("result", {})
        if result.get("approved") is not None:
            return result
    return {}


def _diagnosis_root_cause(context: ToolContext) -> str:
    for subagent in reversed(context.artifacts.get("subagents", [])):
        if subagent.get("kind") != "diagnosis":
            continue
        result = subagent.get("result") or {}
        root_cause = result.get("root_cause")
        if root_cause:
            return str(root_cause)
    return ""


def _failure_category(state: SessionState, runtime_error: Any, review_rejected: bool) -> str | None:
    if runtime_error:
        return str(runtime_error.get("type") or "runtime_error") if isinstance(runtime_error, dict) else "runtime_error"
    if review_rejected:
        return "review_rejected"
    if state.termination_reason == "budget_exhausted":
        return "budget_exhausted"
    if state.validation_status == "failed":
        return "validation_failed"
    return state.termination_reason


def _read_files_from_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for item in history:
        if item.get("tool_name") != "fs.read_file":
            continue
        output = item.get("output") or {}
        path = output.get("path")
        content = output.get("content")
        if path and content is not None:
            files.append({"path": str(path).replace("\\", "/"), "content": str(content)})
    return files


def _has_patch_plan_evidence(files: list[dict[str, str]], context: ToolContext, state: SessionState) -> bool:
    if not files:
        return False
    read_paths = {item["path"].replace("\\", "/") for item in files}
    required_sources = _diagnosis_implicated_source_paths(context)
    if not required_sources:
        required_sources = [
            path.as_posix().replace("\\", "/")
            for path in state.working_set.implicated_sources
            if path.suffix == ".py" and not _is_test_path(path.as_posix())
        ]
    implicated_sources = [path for path in required_sources if (Path(context.repo_root) / path).exists()]
    missing_sources = [path for path in dict.fromkeys(implicated_sources) if path not in read_paths]
    if missing_sources:
        return False
    has_source = any(not _is_test_path(item["path"]) for item in files)
    if not has_source:
        return False
    if any(_is_test_path(item["path"]) for item in files):
        return True
    return bool(context.artifacts.get("subagents"))


def _diagnosis_implicated_source_paths(context: ToolContext) -> list[str]:
    for subagent in reversed(context.artifacts.get("subagents", [])):
        if subagent.get("kind") != "diagnosis":
            continue
        result = subagent.get("result") or {}
        paths = []
        for path in result.get("implicated_files") or []:
            normalized = str(path).replace("\\", "/")
            if normalized.endswith(".py") and not _is_test_path(normalized):
                paths.append(normalized)
        return paths
    return []


def _has_test_and_source(files: list[dict[str, str]]) -> bool:
    has_test = any("/tests/" in f"/{item['path']}" or Path(item["path"]).name.startswith("test_") for item in files)
    has_source = any(not ("/tests/" in f"/{item['path']}" or Path(item["path"]).name.startswith("test_")) for item in files)
    return has_test and has_source
