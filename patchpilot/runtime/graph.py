"""Parent repair runtime."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import ModelBudgetError, PolicyError, ToolError
from patchpilot.models.base import ModelClient, ToolSelection
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.observability.tracing import TraceStore, new_session_id, new_trace_id
from patchpilot.runtime.context import compact_state
from patchpilot.runtime.state import SessionState
from patchpilot.schemas.reports import ChangedFileReport, FinalReport, RepairAttemptReport, TestRunReport
from patchpilot.schemas.tool_io import PatchPlan
from patchpilot.tools import build_registry
from patchpilot.tools.registry import ToolContext
from patchpilot.tools.executor import ToolExecutor


PHASES = ["inspect", "reproduce", "diagnose", "plan_patch", "apply_patch", "validate", "review", "report"]
PHASE_TOOLS = {
    "inspect": {
        "memory_eval.mark_phase",
        "fs.list_dir",
        "code.detect_language",
        "code.detect_package_manager",
        "code.find_tests",
        "exec.detect_test_command",
    },
    "reproduce": {"memory_eval.mark_phase", "exec.run_tests"},
    "diagnose": {
        "memory_eval.mark_phase",
        "code.extract_failure_locations",
        "subagent.spawn_diagnosis",
        "memory_eval.record_observation",
    },
    "plan_patch": {
        "memory_eval.mark_phase",
        "code.map_test_to_source",
        "fs.read_file",
        "memory_eval.store_artifact",
        "code.validate_patch_shape",
        "memory_eval.record_decision",
    },
    "apply_patch": {"memory_eval.mark_phase", "fs.apply_patch"},
    "validate": {"memory_eval.mark_phase", "exec.run_targeted_tests", "exec.run_tests", "git.diff"},
    "review": {
        "memory_eval.mark_phase",
        "subagent.spawn_review",
        "memory_eval.summarize_context",
        "memory_eval.retrieve_artifacts",
    },
    "report": {"memory_eval.mark_phase", "exec.command_history", "memory_eval.export_session"},
}
TOOL_ALIASES = {
    "code.detect_test_command": "exec.detect_test_command",
    "code.run_tests": "exec.run_tests",
    "code.run_targeted_tests": "exec.run_targeted_tests",
    "code.read_file": "fs.read_file",
    "code.read_source": "fs.read_file",
    "code.read_test": "fs.read_file",
    "fs.glob_files": "fs.glob",
    "memory.mark_phase": "memory_eval.mark_phase",
}


class RepairRuntime:
    def __init__(self, config: PatchPilotConfig, model: ModelClient | None = None) -> None:
        self.config = config
        self.registry = build_registry()
        self.model = model or OpenRouterModelClient(config)
        self.trace_store = TraceStore(config.trace_dir)
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
        try:
            while len(state.tool_history) < self.config.max_tool_calls and state.model_calls < self.config.max_model_calls:
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
                if selection.tool_name == "memory_eval.mark_phase":
                    phase = output.text
                    if phase != state.phase:
                        if phase not in PHASES:
                            raise ToolError(f"Invalid phase transition: {phase}")
                        state.phase = phase
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
        await self.trace_store.record(trace_id=trace_id, session_id=session_id, event_type="run.completed", name="patchpilot.run", payload=report.model_dump(mode="json"))
        return report

    def tool_metadata(self, phase: str = "inspect") -> list[dict[str, Any]]:
        return [row.copy() for row in self._phase_metadata.get(phase, self._phase_metadata["inspect"])]

    def _phase_executor(self, phase: str):
        return self._phase_executors.get(phase, self._phase_executors["inspect"])

    def _final_report(self, state: SessionState, context: ToolContext) -> FinalReport:
        tests = [
            TestRunReport(command=item.command, exit_code=item.exit_code, status="passed" if item.exit_code == 0 else "failed")
            for item in context.command_history
        ]
        patch_plan = context.artifacts.get("patch_plan", {})
        runtime_error = context.artifacts.get("runtime_error")
        success = bool(tests and tests[-1].status == "passed" and runtime_error is None)
        model_summary = self._model_summary(state)
        changed_files = self._changed_files(state, patch_plan)
        return FinalReport(
            goal=state.goal,
            status="success" if success else "failed",
            task_classification=patch_plan.get("task_classification", "source_fix"),
            root_cause=patch_plan.get("root_cause", runtime_error["message"] if runtime_error else "Unknown"),
            patch_plan={"summary": patch_plan.get("summary", "")},
            changed_files=changed_files,
            attempts=[RepairAttemptReport(attempt=1, result="passed" if success else "failed", summary=patch_plan.get("summary", "Run validation commands"))],
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
            failure_reason=runtime_error["message"] if runtime_error else None,
        )

    def _prepare_arguments(self, tool_name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if tool_name != "fs.apply_patch":
            return arguments
        patch_plan = context.artifacts.get("patch_plan") or {}
        patch = arguments.get("patch") or patch_plan.get("patch")
        if not patch:
            raise PolicyError("fs.apply_patch requires a validated patch_plan patch")
        validation = context.artifacts.get("patch_validation")
        if not validation or not validation.get("valid"):
            raise PolicyError("fs.apply_patch requires valid patch validation before write")
        return {**arguments, "patch": patch}

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
                and selection.tool_name == "memory_eval.store_artifact"
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
        if not _has_patch_plan_evidence(files, context):
            return
        response = await self.model.complete_json(
            prompt={
                "goal": state.goal,
                "test_command": state.test_command,
                "failure_output": state.last_command_output,
                "recent_tool_history": state.tool_history[-10:],
                "subagents": context.artifacts.get("subagents", []),
                "files": files,
                "requirements": [
                    "Return a minimal source-file patch only.",
                    "Do not edit tests.",
                    "Use a unified diff in the patch field.",
                    "Use repository-relative paths.",
                ],
            },
            schema_name="PatchPlan",
            json_schema=PatchPlan.model_json_schema(),
        )
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
                "target_files": [path.as_posix() for path in (patch_plan.expected_changed_files or [edit.path for edit in patch_plan.edits])],
                "patch": patch_plan.patch,
                "max_diff_lines": self.config.max_diff_lines,
            },
            context,
        )
        state.record_tool("code.validate_patch_shape", validation)
        if not validation.valid:
            raise PolicyError("Patch plan failed validation", {"reasons": validation.reasons})
        state.phase = "apply_patch"
        await self.trace_store.record(
            trace_id=state.trace_id,
            session_id=state.session_id,
            event_type="plan.updated",
            name="apply_patch",
            payload={"phase": "apply_patch", "reason": "validated model patch plan"},
        )

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
        return "memory_eval.mark_phase", {"phase": "reproduce"}
    if state.phase == "reproduce":
        if "exec.run_tests" not in used:
            return "exec.run_tests", {"command": state.test_command} if state.test_command else {}
        return "memory_eval.mark_phase", {"phase": "diagnose"}
    if state.phase == "diagnose":
        if "code.extract_failure_locations" not in used:
            return "code.extract_failure_locations", {"output": state.last_command_output}
        if "subagent.spawn_diagnosis" not in used:
            return "subagent.spawn_diagnosis", {
                "task": "Diagnose the reproduced failing test and identify the smallest source fix.",
                "context": {"test_output": state.last_command_output, "recent_tool_history": state.tool_history[-8:]},
            }
        if "memory_eval.record_observation" not in used:
            return "memory_eval.record_observation", {
                "text": _diagnosis_observation(context),
                "tags": ["diagnosis", "root_cause"],
            }
        return "memory_eval.mark_phase", {"phase": "plan_patch"}
    if state.phase == "plan_patch":
        test_path = _first_test_path(state, context)
        if "code.map_test_to_source" not in used:
            return "code.map_test_to_source", {"path": test_path}
        source_path = _source_candidate(state, context)
        if source_path and not _read_in_phase(state, source_path):
            return "fs.read_file", {"path": source_path}
        if test_path and not _read_in_phase(state, test_path):
            return "fs.read_file", {"path": test_path}
        return None
    if state.phase == "apply_patch":
        if "fs.apply_patch" not in used:
            return "fs.apply_patch", {}
        return "memory_eval.mark_phase", {"phase": "validate"}
    if state.phase == "validate":
        if "exec.run_targeted_tests" not in used:
            target = _first_test_path(state, context)
            return "exec.run_targeted_tests", {"command": f"pytest {target}"} if target else {"command": state.test_command or "pytest"}
        if "exec.run_tests" not in used:
            return "exec.run_tests", {"command": state.test_command or "pytest"}
        if "git.diff" not in used:
            return "git.diff", {}
        return "memory_eval.mark_phase", {"phase": "review"}
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
        if "memory_eval.summarize_context" not in used:
            return "memory_eval.summarize_context", {
                "observations": _review_observations(context),
                "max_chars": 2000,
            }
        if "memory_eval.retrieve_artifacts" not in used:
            return "memory_eval.retrieve_artifacts", {"keys": ["patch_plan", "subagents", "phases"]}
        return "memory_eval.mark_phase", {"phase": "report"}
    if state.phase == "report":
        if "exec.command_history" not in used:
            return "exec.command_history", {}
        if "memory_eval.export_session" not in used:
            return "memory_eval.export_session", {}
    return None


def _used_since_phase_start(state: SessionState) -> set[str]:
    return {item.get("tool_name", "") for item in state.tool_history[_phase_start_index(state) :]}


def _phase_start_index(state: SessionState) -> int:
    for index in range(len(state.tool_history) - 1, -1, -1):
        item = state.tool_history[index]
        if item.get("tool_name") != "memory_eval.mark_phase":
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
    for path in sorted(Path(context.repo_root).rglob(f"{stem}.py")):
        rel = path.relative_to(context.repo_root).as_posix()
        if not _is_test_path(rel):
            return rel
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


def _has_patch_plan_evidence(files: list[dict[str, str]], context: ToolContext) -> bool:
    if not files:
        return False
    has_source = any(not _is_test_path(item["path"]) for item in files)
    if not has_source:
        return False
    if any(_is_test_path(item["path"]) for item in files):
        return True
    return bool(context.artifacts.get("subagents"))


def _has_test_and_source(files: list[dict[str, str]]) -> bool:
    has_test = any("/tests/" in f"/{item['path']}" or Path(item["path"]).name.startswith("test_") for item in files)
    has_source = any(not ("/tests/" in f"/{item['path']}" or Path(item["path"]).name.startswith("test_")) for item in files)
    return has_test and has_source
