"""Smoke eval harness for assignment proof."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

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
    "node_modules",
    "venv",
)


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
        or any(
            event.name == "memory_eval.store_artifact"
            and ((event.payload.get("input") or {}).get("key") == "patch_plan")
            for event in started
        ),
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
    model: str | None = None,
    live_eval: bool = False,
) -> dict[str, Any]:
    work_repo = repo / ".patchpilot" / "eval-work" / uuid4().hex[:8] / "repo"
    shutil.copytree(repo, work_repo, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    config = PatchPilotConfig.from_env(
        repo=work_repo,
        trace_dir=repo / ".patchpilot" / "traces",
        allow_write=True,
        allow_exec=True,
        model_provider=model_provider,
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
    runtime = RepairRuntime(config, model)
    report = await runtime.run("repair failing pytest fixture", test_command="pytest")
    events = runtime.trace_store.read(report.trace_id)
    result = score_trace(events, report, len(build_registry().list()))
    return result | {
        "provider": report.model_provider,
        "model": report.model,
        "report": report.model_dump(mode="json"),
        "cost": report.estimated_cost,
    }
