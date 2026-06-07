"""Smoke and multi-file eval harnesses with blind runtime work copies."""

from __future__ import annotations

import shutil
import time
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, model_validator

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.checks import ordered_phases, trace_tool_checks
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.runtime.graph import PHASES, RepairRuntime
from patchpilot.tools import build_registry

COPY_IGNORE_PATTERNS = (
    ".git",
    ".mypy_cache",
    ".patchpilot",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "fixture.json",
    "node_modules",
    "venv",
)

ProgressCallback = Callable[[dict[str, Any]], None]

GENERIC_REPAIR_GOAL = "Repair the failing pytest suite. Diagnose from tests and source. Apply the smallest source-only fix. Do not edit tests or use fixture metadata."
MANIFEST_PATH = Path(__file__).parent / "manifests" / "suites.json"
ORACLE_FILE_NAMES = {"fixture.json", "suites.json"}
ORACLE_TEXT_MARKERS = (
    "fixture.json",
    "suites.json",
    "expected_changed_files",
    "expected_changed_source_files",
    "allowed_changed_files",
    "minimum_changed_files",
    "expected_validation_commands",
    "patchpilot/evals/manifests",
    "patchpilot\\evals\\manifests",
)


class FixtureMetadata(BaseModel):
    """Post-run fixture oracle metadata; never copied into runtime work repos."""
    name: str
    suite: str = "v2-multifile"
    repo_path: Path = Path(".")
    bug_shape: str = ""
    test_command: str = "pytest"
    expected_changed_source_files: list[Path] = Field(default_factory=list)
    allowed_changed_files: list[Path] = Field(default_factory=list)
    minimum_changed_files: int = 1
    expected_validation_commands: list[str] = Field(default_factory=list)
    expected_failure_category: str | None = None
    flagship: bool = False
    labels: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_changed_file_contract(self) -> "FixtureMetadata":
        expected = [path.as_posix() for path in self.expected_changed_source_files]
        allowed = [path.as_posix() for path in self.allowed_changed_files]
        invalid = [path for path in expected + allowed if _is_test_path(path)]
        if invalid:
            raise ValueError(f"fixture metadata must use source-only changed files: {invalid}")
        if self.minimum_changed_files > len(set(expected)):
            raise ValueError("minimum_changed_files cannot exceed expected changed source files")
        return self


class EvalSuiteManifest(BaseModel):
    fixtures: list[FixtureMetadata]


def score_trace(events: list[Any], report: Any, registry_count: int) -> dict[str, Any]:
    """Score assignment proof from persisted traces and final reports."""
    completed = [event for event in events if event.event_type == "tool.completed"]
    started = [event for event in events if event.event_type == "tool.started"]
    selections = [event for event in events if event.event_type == "model.tool_selection"]
    patch_plans = [event for event in events if event.event_type == "model.patch_plan"]
    structured_subagent_outputs = [event for event in events if event.event_type == "subagent.model.structured_output"]
    trace_checks = trace_tool_checks(events, min_tool_calls=20)
    failed_policy_tools = [
        event for event in completed
        if event.status == "failed" and "requires --allow" in str(event.payload.get("error", ""))
    ]
    checks = {
        "tools_50_plus": registry_count >= 50,
        "tool_calls_20_plus": trace_checks["min_tool_calls"],
        "model_selection_traced": trace_checks["model_selection"],
        "model_patch_plan_traced": bool(patch_plans)
        or any(event.name == "session.store_artifact" and ((event.payload.get("input") or {}).get("key") == "patch_plan") for event in started),
        "model_provider_recorded": bool(getattr(report, "model_provider", None)),
        "subagent_invoked": trace_checks["subagent"],
        "subagent_child_spans": trace_checks["subagent_child_spans"],
        "structured_subagent_output": bool(structured_subagent_outputs) or bool(report.subagents),
        "phase_order_coherent": ordered_phases(events, PHASES),
        "validation_success": any(getattr(test, "status", "") == "passed" for test in report.tests_run),
        "composed_chain": any(event.name == "code.extract_failure_locations" for event in completed)
        and any(event.name == "subagent.spawn_diagnosis" for event in completed)
        and bool(report.changed_files),
        "authorized_tools_only": not failed_policy_tools,
        "final_report_complete": bool(report.trace_id and report.root_cause and report.changed_files),
    }
    score = sum(checks.values()) / len(checks)
    return {"passed": all(checks.values()), "score": score, "checks": checks, "trace_id": report.trace_id}


async def run_smoke_eval(
    repo: Path,
    *,
    model_provider: str = "openrouter",
    model_profile: str | None = None,
    model: str | None = None,
    live_eval: bool = False,
    progress: ProgressCallback | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Run the small eval path through the same OpenRouter runtime contract."""
    _require_openrouter_provider(model_provider)
    metadata = find_fixture_metadata(repo, suite="smoke")
    fixture_name = metadata.name if metadata else repo.name
    test_command = metadata.test_command if metadata else "pytest"
    work_root, work_repo = _copy_fixture_to_work_repo(repo, "smoke", fixture_name)
    config = PatchPilotConfig.from_env(
        repo=work_repo,
        trace_dir=work_root / "traces",
        allow_write=True,
        allow_exec=True,
        blind_eval=True,
        model_provider=model_provider,
        **({"model_profile": model_profile} if model_profile else {}),
        **({"model": model} if model else {}),
        live_eval=live_eval,
    )
    if not config.openrouter_api_key:
        return {
            "passed": False,
            "score": 0.0,
            "checks": {"openrouter_api_key_present": False},
            "failure_reasons": ["OPENROUTER_API_KEY is required for smoke eval with --model-provider openrouter"],
            "provider": "openrouter",
            "model": config.model,
            "runtime_oracle_visible": False,
        }
    model_client = OpenRouterModelClient(config, transport=model_transport)
    runtime = RepairRuntime(config, model_client, progress=progress)
    report = await runtime.run(GENERIC_REPAIR_GOAL, test_command=test_command)
    events = runtime.trace_store.read(report.trace_id)
    blind_audit = audit_runtime_oracle_visibility(events, report)
    result = score_trace(events, report, len(build_registry().list()))
    result["checks"]["runtime_oracle_hidden"] = not blind_audit["runtime_oracle_visible"]
    if blind_audit["runtime_oracle_visible"]:
        result["passed"] = False
        result["failure_reasons"] = ["runtime oracle metadata was visible"]
    return result | {
        "provider": report.model_provider,
        "model": report.model,
        "report": report.model_dump(mode="json"),
        "cost": report.estimated_cost,
        "runtime_oracle_visible": blind_audit["runtime_oracle_visible"],
        "blind_audit": blind_audit,
        "work_repo": str(work_repo),
    }


def load_fixture_metadata(fixture_dir: Path) -> FixtureMetadata:
    metadata = find_fixture_metadata(fixture_dir)
    if metadata is None:
        raise FileNotFoundError(f"No eval manifest entry for fixture: {fixture_dir}")
    return metadata


def load_eval_manifest(path: Path = MANIFEST_PATH) -> EvalSuiteManifest:
    return EvalSuiteManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def iter_manifest_fixtures(*, suite: str | None = None) -> list[FixtureMetadata]:
    fixtures = load_eval_manifest().fixtures
    if suite is None:
        return fixtures
    return [fixture for fixture in fixtures if fixture.suite == suite]


def find_fixture_metadata(fixture_dir: Path, *, suite: str | None = None) -> FixtureMetadata | None:
    fixture_dir = fixture_dir.resolve()
    for metadata in iter_manifest_fixtures(suite=suite):
        if _resolve_fixture_repo(metadata) == fixture_dir:
            return metadata
    return None


def discover_multifile_fixture_metadata(root: Path) -> list[FixtureMetadata]:
    root = root.resolve()
    fixtures: list[FixtureMetadata] = []
    for metadata in iter_manifest_fixtures(suite="v2-multifile"):
        repo = _resolve_fixture_repo(metadata)
        if repo == root or _is_relative_to(repo, root):
            fixtures.append(metadata)
    return sorted(fixtures, key=lambda item: item.name)


def discover_multifile_fixtures(root: Path) -> list[Path]:
    return [_resolve_fixture_repo(metadata) for metadata in discover_multifile_fixture_metadata(root)]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_fixture_repo(metadata: FixtureMetadata) -> Path:
    path = metadata.repo_path
    if path.is_absolute():
        return path.resolve()
    return (_workspace_root() / path).resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _eval_work_root() -> Path:
    return _workspace_root() / "tmp" / "patchpilot-eval-work"


def _copy_fixture_to_work_repo(source_repo: Path, suite: str, fixture_name: str) -> tuple[Path, Path]:
    """Copy a fixture without oracle files so runtime behavior stays blind."""
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in fixture_name)
    work_root = _eval_work_root() / suite / safe_name / uuid4().hex[:8]
    work_repo = work_root / "repo"
    shutil.copytree(source_repo, work_repo, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    violations = _blind_work_repo_violations(work_repo)
    if violations:
        raise RuntimeError("Eval work repo is not blind: " + "; ".join(violations))
    return work_root, work_repo


def _blind_work_repo_violations(work_repo: Path) -> list[str]:
    resolved = work_repo.resolve()
    violations: list[str] = []
    if "fixtures" in resolved.parts:
        violations.append(f"work repo is under fixture ancestry: {resolved}")
    for path in resolved.rglob("*"):
        if path.is_file() and path.name.lower() in ORACLE_FILE_NAMES:
            violations.append(f"oracle file copied into work repo: {path.relative_to(resolved)}")
    return violations


def audit_runtime_oracle_visibility(events: list[Any], report: Any) -> dict[str, Any]:
    """Detect answer-key leakage in prompts, traces, reports, or work paths."""
    violations: list[dict[str, str]] = []
    scanned_items = [(f"trace:{index}:{event.event_type}:{event.name}", event.model_dump(mode="json")) for index, event in enumerate(events)]
    scanned_items.append(("report", report.model_dump(mode="json") if hasattr(report, "model_dump") else report))
    for location, payload in scanned_items:
        text = json.dumps(payload, default=str).lower()
        for marker in ORACLE_TEXT_MARKERS:
            if marker.lower() in text:
                violations.append({"location": location, "marker": marker})
    return {
        "runtime_oracle_visible": bool(violations),
        "violations": violations,
    }


def score_fixture_report(
    report: Any,
    metadata: FixtureMetadata,
    trace_score: dict[str, Any] | None = None,
    *,
    runtime_oracle_visible: bool = False,
) -> dict[str, Any]:
    """Score product behavior first, then report oracle contract diagnostics."""
    changed = {item.path.as_posix() for item in report.changed_files}
    expected = {path.as_posix() for path in metadata.expected_changed_source_files}
    allowed = expected | {path.as_posix() for path in metadata.allowed_changed_files}
    tests = list(getattr(report, "tests_run", []) or [])
    review_result = getattr(report, "review_result", {}) or {}
    product_checks = {
        "report_success": report.status == "success",
        "final_tests_passed": bool(tests and tests[-1].status == "passed"),
        "source_only_changed_files": not any(_is_test_path(path) for path in changed),
        "semantic_validation_visible": bool(getattr(report, "semantic_validation", [])),
        "review_not_rejected": review_result.get("approved") is not False and review_result.get("blocking") is not True,
        "final_report_complete": bool(report.trace_id and tests and report.attempts and report.changed_files),
        "runtime_oracle_hidden": not runtime_oracle_visible,
    }
    product_pass = all(product_checks.values())
    oracle_diagnostics = _oracle_diagnostics(changed, metadata, allowed)
    multi_file_contract = _multi_file_contract(changed, metadata, product_pass, oracle_diagnostics)
    return {
        "passed": product_pass,
        "product_pass": product_pass,
        "checks": product_checks,
        "product_checks": product_checks,
        "changed_files": sorted(changed),
        "expected_changed_source_files": sorted(expected),
        "oracle_diagnostics": oracle_diagnostics,
        "multi_file_contract": multi_file_contract,
    }


async def run_multifile_eval(
    root: Path,
    *,
    model_provider: str = "openrouter",
    model_profile: str | None = None,
    model: str | None = None,
    live_eval: bool = False,
    progress: ProgressCallback | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Run every v2 fixture in a disposable blind workspace."""
    _require_openrouter_provider(model_provider)
    fixtures = discover_multifile_fixture_metadata(root)
    if not fixtures:
        return {"suite": "v2-multifile", "passed": False, "pass_rate": 0.0, "results": [], "failure_reasons": ["no v2 multifile fixtures found"]}
    _emit_progress(progress, event="suite_started", suite="v2-multifile", fixture_count=len(fixtures), root=str(root))
    results: list[dict[str, Any]] = []
    suite_started_at = time.monotonic()
    for index, metadata in enumerate(fixtures, 1):
        fixture = _resolve_fixture_repo(metadata)
        fixture_started_at = time.monotonic()
        _emit_progress(progress, event="fixture_started", fixture=metadata.name, index=index, fixture_count=len(fixtures), bug_shape=metadata.bug_shape)
        config_probe = PatchPilotConfig.from_env(
            repo=fixture,
            model_provider=model_provider,
            **({"model_profile": model_profile} if model_profile else {}),
            **({"model": model} if model else {}),
            live_eval=live_eval,
        )
        if model_provider == "openrouter" and not config_probe.openrouter_api_key:
            _emit_progress(progress, event="fixture_completed", fixture=metadata.name, status="failed", failure_category="missing_api_key", elapsed_seconds=round(time.monotonic() - fixture_started_at, 1))
            expected_allowed = {path.as_posix() for path in metadata.expected_changed_source_files}
            expected_allowed |= {path.as_posix() for path in metadata.allowed_changed_files}
            oracle_diagnostics = _oracle_diagnostics(set(), metadata, expected_allowed)
            results.append(
                {
                    "fixture": metadata.name,
                    "passed": False,
                    "product_pass": False,
                    "product_checks": {"openrouter_api_key_present": False},
                    "failure_category": "missing_api_key",
                    "failure_reason": "OPENROUTER_API_KEY is required for v2 multifile eval with --model-provider openrouter",
                    "model": config_probe.model,
                    "provider": "openrouter",
                    "changed_files": [],
                    "multi_file_contract": _multi_file_contract(set(), metadata, False, oracle_diagnostics),
                    "oracle_diagnostics": oracle_diagnostics,
                    "runtime_oracle_visible": False,
                }
            )
            continue
        work_root, work_repo = _copy_fixture_to_work_repo(fixture, "v2-multifile", metadata.name)
        config = PatchPilotConfig.from_env(
            repo=work_repo,
            trace_dir=work_root / "traces",
            allow_write=True,
            allow_exec=True,
            blind_eval=True,
            model_provider=model_provider,
            **({"model_profile": model_profile} if model_profile else {}),
            **({"model": model} if model else {}),
            live_eval=live_eval,
        )
        runtime_model = OpenRouterModelClient(config, transport=model_transport)
        last_runtime_event: dict[str, Any] = {}

        def runtime_progress(payload: dict[str, Any]) -> None:
            nonlocal last_runtime_event
            last_runtime_event = payload
            _emit_progress(progress, fixture=metadata.name, **payload)

        runtime = RepairRuntime(config, runtime_model, progress=runtime_progress)
        report = await _run_with_heartbeat(runtime, GENERIC_REPAIR_GOAL, metadata.test_command, progress, metadata.name, fixture_started_at, lambda: last_runtime_event)
        events = runtime.trace_store.read(report.trace_id)
        blind_audit = audit_runtime_oracle_visibility(events, report)
        trace_score = score_trace(events, report, len(build_registry().list()))
        fixture_score = score_fixture_report(report, metadata, trace_score, runtime_oracle_visible=blind_audit["runtime_oracle_visible"])
        failure_category = None if fixture_score["passed"] else _categorize_report_failure(report, fixture_score)
        _emit_progress(
            progress,
            event="fixture_completed",
            fixture=metadata.name,
            status="passed" if fixture_score["passed"] else "failed",
            failure_category=failure_category,
            trace_id=report.trace_id,
            report_path=report.report_path,
            retry_count=max(0, len(report.attempts) - 1),
            elapsed_seconds=round(time.monotonic() - fixture_started_at, 1),
        )
        results.append(
            {
                "fixture": metadata.name,
                "bug_shape": metadata.bug_shape,
                "passed": fixture_score["passed"],
                "product_pass": fixture_score["product_pass"],
                "failure_category": failure_category,
                "trace_id": report.trace_id,
                "report_path": report.report_path,
                "trace_path": report.trace_path,
                "provider": report.model_provider,
                "model": report.model,
                "model_calls": report.model_usage_summary.get("model_calls"),
                "tool_calls": report.tool_calls,
                "retry_count": max(0, len(report.attempts) - 1),
                "changed_files": fixture_score["changed_files"],
                "checks": fixture_score["checks"],
                "product_checks": fixture_score["product_checks"],
                "multi_file_contract": fixture_score["multi_file_contract"],
                "oracle_diagnostics": fixture_score["oracle_diagnostics"],
                "runtime_oracle_visible": blind_audit["runtime_oracle_visible"],
                "blind_audit": blind_audit,
                "work_repo": str(work_repo),
                "root_cause": report.root_cause,
                "tests_run": [test.model_dump(mode="json") for test in report.tests_run],
                "rejected_patch_plan_count": len(report.rejected_patch_plans),
                "review_approved": (report.review_result or {}).get("approved"),
                "usage": report.model_usage_summary,
                "cost": report.estimated_cost,
                "cache": report.cache_summary,
            }
        )
    passed_count = sum(1 for result in results if result.get("passed"))
    pass_rate = passed_count / len(results) if results else 0.0
    contract_count = sum(1 for result in results if (result.get("multi_file_contract") or {}).get("contract_matched"))
    contract_rate = contract_count / len(results) if results else 0.0
    runtime_oracle_visible = any(result.get("runtime_oracle_visible") for result in results)
    output = {
        "suite": "v2-multifile",
        "passed": pass_rate >= 0.9 and not runtime_oracle_visible,
        "pass_rate": pass_rate,
        "product_pass_rate": pass_rate,
        "multi_file_contract_match_rate": contract_rate,
        "oracle_match_rate": contract_rate,
        "fixture_count": len(results),
        "passed_count": passed_count,
        "multi_file_contract_matched_count": contract_count,
        "provider": model_provider,
        "model": model or model_profile,
        "runtime_oracle_visible": runtime_oracle_visible,
        "results": results,
    }
    if live_eval:
        output["markdown_report_path"] = str(_write_markdown_eval_report("v2-multifile", output))
    _emit_progress(
        progress,
        event="suite_completed",
        suite="v2-multifile",
        passed_count=passed_count,
        fixture_count=len(results),
        pass_rate=pass_rate,
        multi_file_contract_match_rate=contract_rate,
        markdown_report_path=output.get("markdown_report_path"),
        elapsed_seconds=round(time.monotonic() - suite_started_at, 1),
    )
    return output


async def _run_with_heartbeat(
    runtime: RepairRuntime,
    goal: str,
    test_command: str,
    progress: ProgressCallback | None,
    fixture_name: str,
    started_at: float,
    last_event: Callable[[], dict[str, Any]],
) -> Any:
    import asyncio

    task = asyncio.create_task(runtime.run(goal, test_command=test_command))
    heartbeat_seconds = 30
    while not task.done():
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=heartbeat_seconds)
        except asyncio.TimeoutError:
            last = last_event()
            _emit_progress(
                progress,
                event="heartbeat",
                fixture=fixture_name,
                phase=last.get("phase"),
                trace_id=last.get("trace_id"),
                model_calls=last.get("model_calls"),
                tool_calls=last.get("tool_calls"),
                retry_count=last.get("retry_count"),
                last_event=last.get("event"),
                elapsed_seconds=round(time.monotonic() - started_at, 1),
            )
    return await task


def _emit_progress(progress: ProgressCallback | None, **payload: Any) -> None:
    if progress is None:
        return
    progress(payload)


def _require_openrouter_provider(model_provider: str) -> None:
    if model_provider != "openrouter":
        raise ValueError("PatchPilot eval only supports --model-provider openrouter")


def _categorize_report_failure(report: Any, fixture_score: dict[str, Any]) -> str:
    """Map failed reports to stable eval categories for reviewer triage."""
    if report.failure_reason:
        reason = str(report.failure_reason)
        if "api" in reason.lower():
            return "provider_failure"
        return reason
    checks = fixture_score.get("product_checks", fixture_score.get("checks", {}))
    if not checks.get("runtime_oracle_hidden", True):
        return "runtime_oracle_visible"
    if not checks.get("source_only_changed_files", True):
        return "unsafe_patch"
    if not checks.get("final_tests_passed", True) or (report.tests_run and report.tests_run[-1].status == "failed"):
        return "full_tests_failed"
    if not checks.get("semantic_validation_visible", True):
        return "semantic_validation_missing"
    if not checks.get("review_not_rejected", True):
        return "review_rejected"
    if not checks.get("final_report_complete", True):
        return "final_report_incomplete"
    if not checks.get("report_success", True):
        return "report_status_failed"
    return "model_output_invalid"


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return "/tests/" in f"/{normalized}" or Path(normalized).name.startswith("test_")


def _oracle_diagnostics(changed: set[str], metadata: FixtureMetadata, allowed: set[str]) -> dict[str, Any]:
    expected = {path.as_posix() for path in metadata.expected_changed_source_files}
    unexpected = sorted(changed - allowed)
    return {
        "expected_files_changed": expected.issubset(changed),
        "minimum_changed_files": len(changed & expected) >= metadata.minimum_changed_files,
        "no_unexpected_changed_files": not changed or changed.issubset(allowed),
        "expected_changed_source_files": sorted(expected),
        "allowed_changed_files": sorted(allowed),
        "minimum_required": metadata.minimum_changed_files,
        "unexpected_changed_files": unexpected,
    }


def _multi_file_contract(changed: set[str], metadata: FixtureMetadata, product_pass: bool, oracle_diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Explain whether a passing repair also proved the intended file contract."""
    required = sorted(path.as_posix() for path in metadata.expected_changed_source_files)
    actual = sorted(changed)
    matched = bool(oracle_diagnostics["expected_files_changed"] and oracle_diagnostics["minimum_changed_files"])
    if matched and product_pass:
        note = "Product pass also proved the fixture's intended multi-file contract."
    elif matched:
        note = "Required files changed, but the product repair did not pass."
    elif product_pass:
        note = "Product repair passed, but changed files did not prove this fixture's intended multi-file contract."
    else:
        note = "Repair did not pass and did not prove the fixture's intended multi-file contract."
    return {
        "required_files": required,
        "actual_files": actual,
        "contract_matched": matched,
        "contract_note": note,
    }


def _write_markdown_eval_report(suite: str, result: dict[str, Any]) -> Path:
    report_dir = _eval_work_root() / suite / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "report.md"
    lines = [
        "# PatchPilot V2 Live Eval Report",
        "",
        f"- Suite: `{result.get('suite')}`",
        f"- Provider: `{result.get('provider')}`",
        f"- Model: `{result.get('model')}`",
        f"- Product pass rate: {_pct(result.get('product_pass_rate', result.get('pass_rate', 0.0)))}",
        f"- Multi-file contract match rate: {_pct(result.get('multi_file_contract_match_rate', 0.0))}",
        f"- Fixtures passed: {result.get('passed_count', 0)} / {result.get('fixture_count', 0)}",
        "",
        "## Fixture Summary",
        "",
        "| Fixture | Product | Contract | Failure | Changed files | Trace | Report |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for item in result.get("results", []):
        contract = item.get("multi_file_contract") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(str(item.get("fixture", ""))),
                    "pass" if item.get("product_pass", item.get("passed")) else "fail",
                    "match" if contract.get("contract_matched") else "mismatch",
                    _md(str(item.get("failure_category") or "")),
                    _md(", ".join(item.get("changed_files") or [])),
                    _md(str(item.get("trace_path") or "")),
                    _md(str(item.get("report_path") or "")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Fixture Details", ""])
    for item in result.get("results", []):
        contract = item.get("multi_file_contract") or {}
        oracle = item.get("oracle_diagnostics") or {}
        cache = item.get("cache") or {}
        usage = item.get("usage") or {}
        lines.extend(
            [
                f"### {item.get('fixture')}",
                "",
                f"- Product status: {'pass' if item.get('product_pass', item.get('passed')) else 'fail'}",
                f"- Failure category: `{item.get('failure_category') or ''}`",
                f"- Changed files: `{', '.join(item.get('changed_files') or [])}`",
                f"- Required files: `{', '.join(contract.get('required_files') or [])}`",
                f"- Contract matched: `{bool(contract.get('contract_matched'))}`",
                f"- Contract note: {contract.get('contract_note', '')}",
                f"- Root cause: {item.get('root_cause') or ''}",
                f"- Model calls: `{item.get('model_calls')}`; tool calls: `{item.get('tool_calls')}`; retries: `{item.get('retry_count')}`",
                f"- Cost: `{item.get('cost')}`; cache observed: `{cache.get('observed')}`",
                f"- Tokens: input `{usage.get('input_tokens')}`, output `{usage.get('output_tokens')}`, total `{usage.get('total_tokens')}`",
                f"- Trace: `{item.get('trace_path') or ''}`",
                f"- JSON report: `{item.get('report_path') or ''}`",
                f"- Oracle diagnostics: expected changed `{oracle.get('expected_files_changed')}`, minimum changed `{oracle.get('minimum_changed_files')}`, unexpected files `{', '.join(oracle.get('unexpected_changed_files') or [])}`",
                "",
            ]
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
