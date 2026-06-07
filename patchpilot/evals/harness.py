"""Smoke and multi-file eval harnesses."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.checks import ordered_phases, trace_tool_checks
from patchpilot.models.fake import FakeModelClient
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


class FixtureMetadata(BaseModel):
    name: str
    suite: str = "v2-multifile"
    bug_shape: str
    goal: str
    test_command: str = "pytest"
    expected_changed_source_files: list[Path]
    allowed_changed_files: list[Path] = Field(default_factory=list)
    minimum_changed_files: int = 1
    expected_validation_commands: list[str] = Field(default_factory=list)
    expected_failure_category: str | None = None
    flagship: bool = False

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


def score_trace(events: list[Any], report: Any, registry_count: int) -> dict[str, Any]:
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
) -> dict[str, Any]:
    work_repo = repo / ".patchpilot" / "eval-work" / uuid4().hex[:8] / "repo"
    shutil.copytree(repo, work_repo, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    config = PatchPilotConfig.from_env(
        repo=work_repo,
        trace_dir=repo / ".patchpilot" / "traces",
        allow_write=True,
        allow_exec=True,
        model_provider=model_provider,
        **({"model_profile": model_profile} if model_profile else {}),
        **({"model": model} if model else {}),
        live_eval=live_eval,
    )
    if model_provider == "fake":
        model = FakeModelClient()
    else:
        if not config.openrouter_api_key:
            return {
                "passed": False,
                "score": 0.0,
                "checks": {"openrouter_api_key_present": False},
                "failure_reasons": ["OPENROUTER_API_KEY is required for smoke eval with --model-provider openrouter"],
                "provider": "openrouter",
                "model": config.model,
            }
        model = OpenRouterModelClient(config)
    runtime = RepairRuntime(config, model, progress=progress)
    report = await runtime.run("repair failing pytest fixture", test_command="pytest")
    events = runtime.trace_store.read(report.trace_id)
    result = score_trace(events, report, len(build_registry().list()))
    return result | {
        "provider": report.model_provider,
        "model": report.model,
        "report": report.model_dump(mode="json"),
        "cost": report.estimated_cost,
    }


def load_fixture_metadata(fixture_dir: Path) -> FixtureMetadata:
    import json

    path = fixture_dir / "fixture.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("name", fixture_dir.name)
    return FixtureMetadata.model_validate(data)


def discover_multifile_fixtures(root: Path) -> list[Path]:
    if (root / "fixture.json").exists():
        data = _read_fixture_json(root)
        if data.get("suite") != "v2-multifile":
            return []
        load_fixture_metadata(root)
        return [root]
    fixtures: list[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not (path / "fixture.json").exists():
            continue
        data = _read_fixture_json(path)
        if data.get("suite") == "v2-multifile":
            load_fixture_metadata(path)
            fixtures.append(path)
    return fixtures


def _read_fixture_json(fixture_dir: Path) -> dict[str, Any]:
    import json

    return json.loads((fixture_dir / "fixture.json").read_text(encoding="utf-8"))


def score_fixture_report(report: Any, metadata: FixtureMetadata, trace_score: dict[str, Any] | None = None) -> dict[str, Any]:
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
) -> dict[str, Any]:
    fixtures = discover_multifile_fixtures(root)
    if not fixtures:
        return {"suite": "v2-multifile", "passed": False, "pass_rate": 0.0, "results": [], "failure_reasons": ["no v2 multifile fixtures found"]}
    _emit_progress(progress, event="suite_started", suite="v2-multifile", fixture_count=len(fixtures), root=str(root))
    results: list[dict[str, Any]] = []
    suite_started_at = time.monotonic()
    for index, fixture in enumerate(fixtures, 1):
        metadata = load_fixture_metadata(fixture)
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
        work_repo = fixture / ".patchpilot" / "eval-work" / uuid4().hex[:8] / "repo"
        shutil.copytree(fixture, work_repo, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
        config = PatchPilotConfig.from_env(
            repo=work_repo,
            trace_dir=fixture / ".patchpilot" / "traces",
            allow_write=True,
            allow_exec=True,
            model_provider=model_provider,
            **({"model_profile": model_profile} if model_profile else {}),
            **({"model": model} if model else {}),
            live_eval=live_eval,
        )
        runtime_model = FakeModelClient() if model_provider == "fake" else OpenRouterModelClient(config)
        last_runtime_event: dict[str, Any] = {}

        def runtime_progress(payload: dict[str, Any]) -> None:
            nonlocal last_runtime_event
            last_runtime_event = payload
            _emit_progress(progress, fixture=metadata.name, **payload)

        runtime = RepairRuntime(config, runtime_model, progress=runtime_progress)
        report = await _run_with_heartbeat(runtime, metadata.goal, metadata.test_command, progress, metadata.name, fixture_started_at, lambda: last_runtime_event)
        events = runtime.trace_store.read(report.trace_id)
        trace_score = score_trace(events, report, len(build_registry().list()))
        fixture_score = score_fixture_report(report, metadata, trace_score)
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
                "runtime_oracle_visible": False,
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
    output = {
        "suite": "v2-multifile",
        "passed": pass_rate >= 0.9,
        "pass_rate": pass_rate,
        "product_pass_rate": pass_rate,
        "multi_file_contract_match_rate": contract_rate,
        "oracle_match_rate": contract_rate,
        "fixture_count": len(results),
        "passed_count": passed_count,
        "multi_file_contract_matched_count": contract_count,
        "provider": model_provider,
        "model": model or model_profile,
        "runtime_oracle_visible": False,
        "results": results,
    }
    if live_eval:
        output["markdown_report_path"] = str(_write_markdown_eval_report(root, output))
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


def _categorize_report_failure(report: Any, fixture_score: dict[str, Any]) -> str:
    if report.failure_reason:
        reason = str(report.failure_reason)
        if "api" in reason.lower():
            return "provider_failure"
        return reason
    checks = fixture_score.get("product_checks", fixture_score.get("checks", {}))
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


def _write_markdown_eval_report(root: Path, result: dict[str, Any]) -> Path:
    report_dir = root / ".patchpilot" / "reports"
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
