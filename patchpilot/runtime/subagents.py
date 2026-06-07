"""Scoped diagnosis and review subagent runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from patchpilot.adapters.python_pytest import PythonPytestAdapter
from patchpilot.errors import (
    ExecutionTimeoutError,
    ModelBudgetError,
    ModelError,
    ModelResponseError,
    ModelSchemaError,
    PolicyError,
    SubagentError,
    ToolError,
)
from patchpilot.models.base import ModelClient
from patchpilot.runtime.state import SessionState
from patchpilot.schemas.tool_io import DiagnosisResult, ReviewResult, SubagentConfig, SubagentResultOutput
from patchpilot.tools.helpers import grep_text, read_text, rel_path, repo_path
from patchpilot.tools.registry import ToolContext


SUBAGENT_CONFIGS = {
    # Subagents get read-only, task-specific tools so they can add judgment
    # without bypassing the parent runtime's write gate.
    "diagnosis": SubagentConfig(
        kind="diagnosis",
        allowed_tools=[
            "code.extract_failure_locations",
            "code.map_test_to_source",
            "code.search_text",
            "code.parse_imports",
            "code.build_file_bundle",
            "fs.list_dir",
            "fs.glob",
            "fs.read_file",
            "fs.read_files",
            "session.retrieve_artifacts",
        ],
        max_model_calls=3,
        max_tool_calls=8,
        output_schema="DiagnosisResult",
    ),
    "review": SubagentConfig(
        kind="review",
        allowed_tools=[
            "git.diff",
            "exec.command_history",
            "session.retrieve_artifacts",
            "fs.read_file",
            "fs.read_files",
        ],
        max_model_calls=2,
        max_tool_calls=6,
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
        """Run one bounded child loop and return structured output to the parent."""
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
        # Child spans share the trace ID but use a scoped session ID, making the
        # parent/subagent boundary visible in JSONL traces.
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
        if kind == "diagnosis":
            result = await self._run_diagnosis(config, task, evidence, scoped, child_context, tool_evidence)
        elif kind == "review":
            # Review may inspect the final diff and artifacts, but cannot write.
            if self.model is not None:
                await self._run_model_loop(config, task, evidence, scoped, child_context, tool_evidence)
            output = await ToolExecutor(scoped).execute("git.diff", {}, child_context)
            tool_evidence["diff_exit_code"] = output.exit_code
            if self.model is not None:
                result = await self._structured_review(task, evidence, tool_evidence, child_context)
            else:
                result = ReviewResult(
                    approved=True,
                    issues=[],
                    evidence=tool_evidence,
                    regression_risk="low",
                    missing_validation=[],
                    changed_file_necessity={},
                    blocking=False,
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

    async def _run_diagnosis(
        self,
        config: SubagentConfig,
        task: str,
        evidence: dict[str, Any],
        registry,
        child_context: ToolContext,
        tool_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        from patchpilot.tools.executor import ToolExecutor

        executor = ToolExecutor(registry)
        failure_output = _evidence_output(evidence)
        output = await executor.execute(
            "code.extract_failure_locations",
            {"output": failure_output},
            child_context,
        )
        tool_evidence["failure_locations"] = output.model_dump(mode="json")
        if self.model is None:
            return _default_diagnosis(evidence, tool_evidence).model_dump(mode="json")

        attempt_failures = await self._run_model_loop(config, task, evidence, registry, child_context, tool_evidence)
        if attempt_failures:
            tool_evidence["subagent_attempt_failures"] = attempt_failures
        try:
            return await self._structured_diagnosis(task, evidence, tool_evidence, child_context)
        except Exception as exc:
            first_failure = _failure_record(exc)
            tool_evidence["structured_diagnosis_error"] = first_failure
            recovery_context = _gather_diagnosis_recovery_context(
                Path(child_context.repo_root),
                evidence,
                tool_evidence,
                [*attempt_failures, first_failure],
            )
            await self._trace_recovery(child_context, "subagent.recovery.started", recovery_context)

        retry_evidence = {
            **evidence,
            "diagnosis_recovery": recovery_context,
            "diagnosis_recovery_warning": "Use only existing paths from source_candidates unless you first discover new paths.",
        }
        retry_failures = await self._run_model_loop(
            config,
            task,
            retry_evidence,
            registry,
            child_context,
            tool_evidence,
            recovery_context=recovery_context,
            recovery_warning="Use only existing paths from source_candidates unless you first discover new paths.",
            evidence_prefix="retry_model_tool",
        )
        if retry_failures:
            tool_evidence["subagent_retry_failures"] = retry_failures
        try:
            result = await self._structured_diagnosis(task, retry_evidence, tool_evidence, child_context)
            result["recovery"] = {
                "used": True,
                "fallback_used": False,
                "failure_category": recovery_context.get("failure_category"),
                "source_candidates": recovery_context.get("source_candidates", []),
            }
            await self._trace_recovery(child_context, "subagent.recovery.completed", result["recovery"])
            return result
        except Exception as exc:
            retry_failure = _failure_record(exc)
            tool_evidence["diagnosis_retry_error"] = retry_failure
            recovery_context = _gather_diagnosis_recovery_context(
                Path(child_context.repo_root),
                retry_evidence,
                tool_evidence,
                [*attempt_failures, *retry_failures, retry_failure],
            )
            if not recovery_context.get("sufficient_evidence"):
                await self._trace_recovery(child_context, "subagent.recovery.failed", recovery_context)
                raise
            result = _fallback_diagnosis(recovery_context, tool_evidence).model_dump(mode="json")
            result["recovery"] = {
                "used": True,
                "fallback_used": True,
                "failure_category": recovery_context.get("failure_category"),
                "source_candidates": recovery_context.get("source_candidates", []),
            }
            await self._trace_recovery(child_context, "subagent.recovery.completed", result["recovery"])
            return result

    async def _trace_recovery(self, child_context: ToolContext, event_type: str, payload: dict[str, Any]) -> None:
        if child_context.trace_store:
            await child_context.trace_store.record(
                trace_id=child_context.trace_id,
                session_id=child_context.session_id,
                event_type=event_type,
                name="diagnosis",
                payload=payload,
            )

    async def _run_model_loop(
        self,
        config: SubagentConfig,
        task: str,
        evidence: dict[str, Any],
        registry,
        child_context: ToolContext,
        tool_evidence: dict[str, Any],
        recovery_context: dict[str, Any] | None = None,
        recovery_warning: str = "",
        evidence_prefix: str = "model_tool",
    ) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        if self.model is None:
            return failures
        from patchpilot.tools.executor import ToolExecutor

        state = SessionState(repo=child_context.repo_root, goal=task, phase=config.kind, session_id=child_context.session_id, trace_id=child_context.trace_id)
        _seed_subagent_state(state, evidence, recovery_context, recovery_warning)
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
                failure = {
                    "category": "invalid_tool_selection",
                    "tool": selection.tool_name,
                    "arguments": selection.arguments,
                    "error_type": "ToolError",
                    "error": f"Tool is not allowed in {config.kind}: {selection.tool_name}",
                }
                failures.append(failure)
                tool_evidence[f"{evidence_prefix}_{index + 1}"] = failure
                state.tool_history.append({"tool_name": selection.tool_name, "output": failure})
                break
            try:
                output = await executor.execute(selection.tool_name, selection.arguments, child_context)
            except Exception as exc:
                error = {
                    "tool": selection.tool_name,
                    "arguments": selection.arguments,
                    "category": _classify_diagnosis_failure(exc),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                failures.append(error)
                tool_evidence[f"{evidence_prefix}_{index + 1}"] = error
                state.tool_history.append({"tool_name": selection.tool_name, "output": error})
                if child_context.trace_store:
                    await child_context.trace_store.record(
                        trace_id=child_context.trace_id,
                        session_id=child_context.session_id,
                        event_type="subagent.tool.failed",
                        name=selection.tool_name,
                        status="failed",
                        payload=error,
                    )
                continue
            state.record_tool(selection.tool_name, output)
            _append_seed_context(state)
            tool_evidence[f"{evidence_prefix}_{index + 1}"] = {"tool": selection.tool_name, "output": output.model_dump(mode="json")}
            if len(state.tool_history) >= config.max_tool_calls:
                if child_context.trace_store:
                    await child_context.trace_store.record(
                        trace_id=child_context.trace_id,
                        session_id=child_context.session_id,
                        event_type="subagent.budget_exhausted",
                        name=config.kind,
                        status="failed",
                        payload={"max_tool_calls": config.max_tool_calls},
                    )
                failure = {
                    "category": "tool_budget_exhausted",
                    "error_type": "ModelBudgetError",
                    "error": f"{config.kind} subagent exhausted max_tool_calls={config.max_tool_calls}",
                }
                failures.append(failure)
                tool_evidence[f"{evidence_prefix}_{index + 1}_budget"] = failure
                break
        return failures

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
                    "Link every implicated file to evidence and the same shared root cause.",
                    "Do not assume any fixture-specific answer. Infer implicated files only from visible evidence.",
                    "If diagnosis_recovery is present, use only existing paths from source_candidates unless visible evidence discovers a new path.",
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
                    "Check whether every changed file is necessary for the diagnosed root cause.",
                    "Reject correctness, necessity, or serious regression-risk issues by setting approved false.",
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


def _failure_output_files(output: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for match in re.findall(r"([A-Za-z0-9_./\\-]+\.py)(?::\d+)?", output):
        normalized = match.replace("\\", "/")
        if normalized in seen or "/tests/" in f"/{normalized}" or normalized.split("/")[-1].startswith("test_"):
            continue
        seen.add(normalized)
        paths.append(normalized)
    return paths


def _default_diagnosis(evidence: dict[str, Any], tool_evidence: dict[str, Any]) -> DiagnosisResult:
    output = _evidence_output(evidence)
    implicated_files = _failure_output_files(output)
    if not implicated_files:
        implicated_files = _source_file_hints_from_evidence(evidence)[:5]
    return DiagnosisResult(
        root_cause="A source implementation appears inconsistent with the reproduced test failure.",
        evidence=tool_evidence,
        evidence_links=[],
        implicated_files=[Path(path) for path in implicated_files],
        shared_root_cause="Reproduced failure and implicated source files point to one repair hypothesis.",
        recommended_patch_direction="Inspect implicated source and tests, then apply the smallest source-only fix.",
        confidence=0.5,
        risks=[],
    )


def _fallback_diagnosis(recovery_context: dict[str, Any], tool_evidence: dict[str, Any]) -> DiagnosisResult:
    candidates = [Path(path) for path in recovery_context.get("source_candidates", [])]
    root_cause = recovery_context.get("root_cause_hypothesis") or (
        "Diagnosis model failed, but failing tests and import-resolved source candidates provide enough repo-grounded evidence to continue."
    )
    evidence = {
        **tool_evidence,
        "diagnosis_recovery": recovery_context,
    }
    return DiagnosisResult(
        root_cause=root_cause,
        evidence=evidence,
        evidence_links=[],
        implicated_files=candidates,
        shared_root_cause=root_cause,
        recommended_patch_direction=(
            "Use the recovered failing test snippets and existing source_candidates only; read any missing candidate source before applying "
            "the smallest source-only fix."
        ),
        confidence=0.35,
        risks=["Structured model diagnosis failed; this deterministic recovery diagnosis is lower confidence."],
    )


def _seed_subagent_state(
    state: SessionState,
    evidence: dict[str, Any],
    recovery_context: dict[str, Any] | None,
    recovery_warning: str,
) -> None:
    output = _evidence_output(evidence)
    state.last_command_output = output
    source_hints = _source_file_hints_from_evidence(evidence)
    failing_tests = _failing_tests_from_evidence(Path(state.repo), evidence)
    source_candidates = list(recovery_context.get("source_candidates", [])) if recovery_context else source_hints
    for path in failing_tests:
        _append_unique_path(state.working_set.relevant_tests, Path(path))
    for path in source_candidates:
        _append_unique_path(state.working_set.implicated_sources, Path(path))
    if source_hints:
        state.working_set.summaries["source_file_hints"] = "\n".join(source_hints[:40])
    seed_payload = {
        "failing_output": output,
        "failing_tests": failing_tests,
        "source_file_hints": source_hints[:40],
        "failed_read_paths": _failed_paths_from_evidence(evidence),
        "prior_subagent_errors": _prior_subagent_errors_from_evidence(evidence),
        "recovery_warning": recovery_warning,
        "recovery_context": recovery_context or {},
    }
    context_text = json.dumps(seed_payload, indent=2, default=str)
    state.working_set.summaries["subagent_context"] = context_text
    state.last_text_output = context_text


def _gather_diagnosis_recovery_context(
    root: Path,
    evidence: dict[str, Any],
    tool_evidence: dict[str, Any],
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    adapter = PythonPytestAdapter()
    output = _evidence_output(evidence)
    failure_locations = adapter.failure_locations(output)
    failing_tests = _existing_failing_tests(root, output, failure_locations)
    test_snippets: dict[str, str] = {}
    imports_by_test: dict[str, list[str]] = {}
    source_candidates: list[str] = []
    for test_path in failing_tests:
        text = _safe_read_repo_file(root, test_path)
        if text is None:
            continue
        test_key = test_path.as_posix()
        test_snippets[test_key] = _clip(text, 2200)
        imports_by_test[test_key] = _parse_imports(text)
        for candidate in adapter.source_candidates_for_test(root, test_path):
            if _is_existing_source_path(root, candidate):
                source_candidates.append(candidate.as_posix())

    if not source_candidates:
        for hint in _source_file_hints_from_evidence(evidence):
            hint_path = Path(hint)
            if _is_existing_source_path(root, hint_path):
                source_candidates.append(hint_path.as_posix())

    search_hits: list[dict[str, Any]] = []
    for symbol in _recovery_symbols(output, test_snippets):
        for path, line, snippet in grep_text(root, symbol, 5):
            rel = rel_path(root, path)
            if _is_test_path(rel.as_posix()):
                continue
            search_hits.append({"symbol": symbol, "file_path": rel.as_posix(), "line": line, "snippet": snippet})
            if _is_existing_source_path(root, rel):
                source_candidates.append(rel.as_posix())
        if len(search_hits) >= 20:
            break

    source_candidates = _dedupe(source_candidates)[:12]
    source_snippets: dict[str, str] = {}
    for candidate in source_candidates:
        text = _safe_read_repo_file(root, Path(candidate))
        if text is not None:
            source_snippets[candidate] = _clip(text, 2200)

    failed_attempts = [*_failed_tool_attempts(tool_evidence), *failures]
    failure_category = _dominant_failure_category(failed_attempts)
    root_cause_hypothesis = _deterministic_root_cause_hypothesis(failing_tests, source_candidates, imports_by_test, failure_category)
    sufficient_evidence = bool(test_snippets) and bool(source_snippets) and bool(root_cause_hypothesis)
    return {
        "failure_category": failure_category,
        "original_failing_output": _clip(output, 5000),
        "failure_locations": failure_locations,
        "failing_tests": [path.as_posix() for path in failing_tests],
        "test_snippets": test_snippets,
        "imports_by_test": imports_by_test,
        "source_candidates": list(source_snippets.keys()),
        "source_snippets": source_snippets,
        "search_hits": search_hits[:20],
        "failed_attempts": failed_attempts,
        "rejected_or_missing_paths": _rejected_or_missing_paths(failed_attempts, tool_evidence),
        "source_file_hints": _source_file_hints_from_evidence(evidence)[:40],
        "root_cause_hypothesis": root_cause_hypothesis,
        "sufficient_evidence": sufficient_evidence,
    }


def _evidence_output(evidence: dict[str, Any]) -> str:
    for key in ("output", "test_output", "failing_output", "failure_output", "stderr", "stdout"):
        value = evidence.get(key)
        if value:
            return str(value)
    for item in evidence.get("recent_tool_history") or []:
        output = item.get("output") if isinstance(item, dict) else None
        if isinstance(output, dict):
            text = "\n".join(str(output.get(key, "")) for key in ("stdout", "stderr"))
            if text.strip():
                return text
    return ""


def _failure_record(exc: Exception) -> dict[str, Any]:
    return {
        "category": _classify_diagnosis_failure(exc),
        "error_type": type(exc).__name__,
        "error": str(exc),
    }


def _classify_diagnosis_failure(exc: Exception | dict[str, Any]) -> str:
    if isinstance(exc, dict):
        text = f"{exc.get('error_type', '')} {exc.get('error', '')} {exc.get('category', '')}".lower()
        error_type = str(exc.get("error_type") or "")
    else:
        text = f"{type(exc).__name__} {exc}".lower()
        error_type = type(exc).__name__
    if isinstance(exc, ModelBudgetError) or "budget" in text or "max_tool_calls" in text:
        return "tool_budget_exhaustion"
    if isinstance(exc, ExecutionTimeoutError) or "timeout" in text or "timed out" in text:
        return "provider_empty_response_timeout"
    if isinstance(exc, FileNotFoundError) or "no such file" in text or "not found" in text or "missing" in text:
        return "missing_file_path_guess"
    if isinstance(exc, PolicyError) or "path escapes" in text:
        return "missing_file_path_guess"
    if "not allowed" in text or "unknown tool" in text or "rejected_tool" in text or error_type == "ToolError":
        return "invalid_tool_selection"
    if isinstance(exc, ModelSchemaError) or "schema" in text or "validation" in text:
        return "model_schema_failure"
    if isinstance(exc, ModelResponseError) or isinstance(exc, ModelError) or "empty message" in text or "empty response" in text:
        return "provider_empty_response_timeout"
    return "model_schema_failure"


def _existing_failing_tests(root: Path, output: str, failure_locations: list[dict[str, Any]]) -> list[Path]:
    candidates: list[str] = []
    for location in failure_locations:
        file_path = str(location.get("file") or "")
        if file_path:
            candidates.append(file_path)
    candidates.extend(re.findall(r"([A-Za-z0-9_./\\-]*tests[/\\][A-Za-z0-9_./\\-]+\.py)(?::\d+)?", output))
    candidates.extend(re.findall(r"([A-Za-z0-9_./\\-]*test_[A-Za-z0-9_./\\-]+\.py)(?::\d+)?", output))
    paths: list[Path] = []
    for candidate in candidates:
        normalized = candidate.replace("\\", "/").lstrip("./")
        path = Path(normalized)
        if not _is_test_path(path.as_posix()):
            continue
        try:
            resolved = repo_path(root, path)
        except PolicyError:
            continue
        if resolved.exists() and resolved.is_file():
            _append_unique_path(paths, rel_path(root, resolved))
    return paths


def _failing_tests_from_evidence(root: Path, evidence: dict[str, Any]) -> list[str]:
    output = _evidence_output(evidence)
    return [path.as_posix() for path in _existing_failing_tests(root, output, PythonPytestAdapter().failure_locations(output))]


def _safe_read_repo_file(root: Path, path: Path) -> str | None:
    try:
        resolved = repo_path(root, path)
        if not resolved.exists() or not resolved.is_file():
            return None
        return read_text(resolved)
    except (OSError, PolicyError):
        return None


def _is_existing_source_path(root: Path, path: Path) -> bool:
    try:
        resolved = repo_path(root, path)
    except PolicyError:
        return False
    rel = rel_path(root, resolved)
    return resolved.exists() and resolved.is_file() and rel.suffix == ".py" and not _is_test_path(rel.as_posix())


def _parse_imports(text: str) -> list[str]:
    imports: list[str] = []
    for match in re.finditer(r"from\s+([A-Za-z0-9_.]+)\s+import|import\s+([A-Za-z0-9_.]+)", text):
        module = next(group for group in match.groups() if group)
        imports.append(module)
    return _dedupe(imports)


def _recovery_symbols(output: str, test_snippets: dict[str, str]) -> list[str]:
    text = "\n".join([output, *test_snippets.values()])
    ignored = {
        "AssertionError",
        "FAILED",
        "File",
        "line",
        "from",
        "import",
        "True",
        "False",
        "None",
        "pytest",
    }
    symbols: list[str] = []
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", text):
        if token in ignored or token.startswith("test_"):
            continue
        symbols.append(token)
    return _dedupe(symbols)[:8]


def _failed_tool_attempts(tool_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for key, value in tool_evidence.items():
        if "model_tool" not in str(key):
            continue
        if not isinstance(value, dict):
            continue
        if value.get("error") or value.get("error_type"):
            attempts.append(value)
            continue
        output = value.get("output")
        if not isinstance(output, dict):
            continue
        for error in output.get("errors") or []:
            if isinstance(error, dict):
                attempts.append(
                    {
                        "tool": value.get("tool"),
                        "path": error.get("path"),
                        "category": _classify_diagnosis_failure(error),
                        "error_type": error.get("error_type"),
                        "error": error.get("error"),
                    }
                )
    return attempts


def _rejected_or_missing_paths(failed_attempts: list[dict[str, Any]], tool_evidence: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for attempt in failed_attempts:
        path = attempt.get("path")
        if path:
            paths.append(str(path))
        arguments = attempt.get("arguments")
        if isinstance(arguments, dict):
            if arguments.get("path"):
                paths.append(str(arguments["path"]))
            for item in arguments.get("paths") or []:
                paths.append(str(item))
    for value in tool_evidence.values():
        if not isinstance(value, dict):
            continue
        output = value.get("output")
        if isinstance(output, dict):
            paths.extend(str(path) for path in output.get("missing_files") or [])
    return _dedupe(paths)


def _dominant_failure_category(failed_attempts: list[dict[str, Any]]) -> str:
    for attempt in failed_attempts:
        category = attempt.get("category")
        if category:
            return str(category)
    return "model_schema_failure"


def _deterministic_root_cause_hypothesis(
    failing_tests: list[Path],
    source_candidates: list[str],
    imports_by_test: dict[str, list[str]],
    failure_category: str,
) -> str:
    if not failing_tests or not source_candidates:
        return ""
    test_list = ", ".join(path.as_posix() for path in failing_tests[:3])
    source_list = ", ".join(source_candidates[:5])
    import_list = ", ".join(_dedupe([item for imports in imports_by_test.values() for item in imports])[:8])
    imported = f" imported modules ({import_list})" if import_list else ""
    return (
        f"Diagnosis failed after {failure_category}, but failing tests {test_list}{imported} resolve to existing source "
        f"candidates {source_list}; the repair should be grounded in those files."
    )


def _source_file_hints_from_evidence(evidence: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for key in ("source_file_hints", "source_hints"):
        value = evidence.get(key)
        if isinstance(value, list):
            hints.extend(str(item) for item in value)
    recovery = evidence.get("diagnosis_recovery")
    if isinstance(recovery, dict):
        value = recovery.get("source_candidates") or recovery.get("source_file_hints")
        if isinstance(value, list):
            hints.extend(str(item) for item in value)
    return _dedupe([hint.replace("\\", "/") for hint in hints if str(hint).endswith(".py")])


def _failed_paths_from_evidence(evidence: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in evidence.get("recent_tool_history") or []:
        output = item.get("output") if isinstance(item, dict) else None
        if isinstance(output, dict):
            paths.extend(str(path) for path in output.get("missing_files") or [])
            for error in output.get("errors") or []:
                if isinstance(error, dict) and error.get("path"):
                    paths.append(str(error["path"]))
    return _dedupe(paths)


def _prior_subagent_errors_from_evidence(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for item in evidence.get("recent_tool_history") or []:
        output = item.get("output") if isinstance(item, dict) else None
        if isinstance(output, dict) and (output.get("error") or output.get("error_type")):
            errors.append(output)
    return errors


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return "/tests/" in f"/{normalized}" or name.startswith("test_")


def _append_unique_path(paths: list[Path], path: Path) -> None:
    normalized = Path(path.as_posix())
    if normalized not in paths:
        paths.append(normalized)


def _append_seed_context(state: SessionState) -> None:
    context_text = state.working_set.summaries.get("subagent_context", "")
    if context_text and context_text not in state.last_text_output:
        state.last_text_output = f"{state.last_text_output}\n\nSubagent context:\n{context_text}"


def _clip(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
