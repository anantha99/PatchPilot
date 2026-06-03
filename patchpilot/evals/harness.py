"""Smoke eval harness for assignment proof."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from patchpilot.config import PatchPilotConfig
from patchpilot.models.fake import FakeModelClient
from patchpilot.runtime.graph import PHASES, RepairRuntime
from patchpilot.tools import build_registry


def score_trace(events: list[Any], report: Any, registry_count: int) -> dict[str, Any]:
    completed = [event for event in events if event.event_type == "tool.completed"]
    selections = [event for event in events if event.event_type == "model.tool_selection"]
    phases = [event.name for event in events if event.event_type == "plan.updated"]
    checks = {
        "tools_50_plus": registry_count >= 50,
        "tool_calls_20_plus": len(completed) >= 20,
        "model_selection_traced": len(selections) >= 20,
        "subagent_invoked": any(event.name.startswith("subagent.") for event in completed),
        "phase_order_coherent": all(phase in PHASES for phase in phases) and "validate" in phases,
        "validation_success": any(getattr(test, "status", "") == "passed" for test in report.tests_run),
        "composed_chain": any(event.name == "code.extract_failure_locations" for event in completed) and any(event.name == "subagent.spawn_diagnosis" for event in completed),
        "final_report_complete": bool(report.trace_id and report.root_cause and report.changed_files),
    }
    score = sum(checks.values()) / len(checks)
    return {"passed": all(checks.values()), "score": score, "checks": checks, "trace_id": report.trace_id}


async def run_smoke_eval(repo: Path) -> dict[str, Any]:
    work_repo = repo / ".patchpilot" / "eval-work" / "repo"
    if work_repo.parent.exists():
        shutil.rmtree(work_repo.parent)
    shutil.copytree(repo, work_repo, ignore=shutil.ignore_patterns(".patchpilot", "__pycache__"))
    config = PatchPilotConfig(repo=work_repo, trace_dir=repo / ".patchpilot" / "traces", allow_write=True, allow_exec=True)
    runtime = RepairRuntime(config, FakeModelClient())
    report = await runtime.run("repair failing pytest fixture", test_command="pytest")
    events = runtime.trace_store.read(report.trace_id)
    return score_trace(events, report, len(build_registry().list())) | {"report": report.model_dump(mode="json")}
