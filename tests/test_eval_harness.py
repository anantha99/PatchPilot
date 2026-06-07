"""Eval harness tests for blind fixtures, trace scoring, and oracle diagnostics."""

from pathlib import Path
import asyncio
import shutil

import pytest

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.suites import run_suite
from patchpilot.evals.harness import (
    COPY_IGNORE_PATTERNS,
    GENERIC_REPAIR_GOAL,
    FixtureMetadata,
    _blind_work_repo_violations,
    _copy_fixture_to_work_repo,
    audit_runtime_oracle_visibility,
    discover_multifile_fixtures,
    iter_manifest_fixtures,
    load_fixture_metadata,
    score_fixture_report,
    score_trace,
)
from patchpilot.models.openrouter import OpenRouterModelClient
from patchpilot.runtime.graph import RepairRuntime
from patchpilot.schemas.reports import ChangedFileReport, FinalReport, RepairAttemptReport, TestRunReport, TraceEvent
from tests.support.openrouter_mock import SchemaAwareOpenRouterTransport


def test_eval_score_fails_when_trace_lacks_assignment_proof() -> None:
    report = FinalReport(
        goal="repair",
        status="failed",
        task_classification="source_fix",
        root_cause="unknown",
        patch_plan={"summary": "none"},
        changed_files=[ChangedFileReport(path="x.py", change_type="modify", justification="test")],
        attempts=[RepairAttemptReport(attempt=1, result="failed", summary="failed")],
        tests_run=[TestRunReport(command="pytest", exit_code=1, status="failed")],
        subagents=[],
        risks=[],
        trace_id="tr_test",
    )
    events = [TraceEvent(trace_id="tr_test", session_id="s", event_type="tool.completed", name="fs.list_dir")]

    result = score_trace(events, report, registry_count=50)

    assert result["passed"] is False
    assert result["checks"]["tool_calls_20_plus"] is False


def test_eval_manifest_covers_smoke_and_multifile_fixtures() -> None:
    smoke = iter_manifest_fixtures(suite="smoke")
    multifile = iter_manifest_fixtures(suite="v2-multifile")

    assert {fixture.name for fixture in smoke} >= {"buggy-python-repo", "mock-store-python", "buggy-parser-repo", "buggy-validation-repo"}
    assert len(multifile) >= 10
    assert all(fixture.expected_changed_source_files for fixture in multifile)
    assert all(fixture.test_command == "pytest" for fixture in smoke + multifile)


def test_multifile_fixture_metadata_is_discoverable_and_source_only() -> None:
    fixtures = discover_multifile_fixtures(Path(__file__).parents[1] / "fixtures")

    assert len(fixtures) >= 10
    assert all(load_fixture_metadata(fixture).suite == "v2-multifile" for fixture in fixtures)


def test_source_fixture_repos_do_not_contain_oracle_metadata() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    manifest_repos = [Path(__file__).parents[1] / fixture.repo_path for fixture in iter_manifest_fixtures()]

    assert manifest_repos
    assert all(not (repo / "fixture.json").exists() for repo in manifest_repos)
    assert all(fixture_root in repo.parents for repo in manifest_repos)


def test_fixture_metadata_rejects_test_expected_changes() -> None:
    with pytest.raises(ValueError):
        FixtureMetadata(
            name="bad",
            bug_shape="test edit",
            goal="bad",
            expected_changed_source_files=[Path("tests/test_app.py")],
        )


def test_fixture_report_scoring_accepts_product_pass_with_contract_mismatch() -> None:
    metadata = FixtureMetadata(
        name="contract",
        bug_shape="contract drift",
        goal="repair",
        expected_changed_source_files=[Path("pkg/a.py"), Path("pkg/b.py")],
        minimum_changed_files=2,
    )
    report = FinalReport(
        goal="repair",
        status="success",
        task_classification="source_fix",
        root_cause="contract drift",
        patch_plan={"summary": "partial"},
        changed_files=[ChangedFileReport(path=Path("pkg/a.py"), change_type="modify", justification="test")],
        attempts=[RepairAttemptReport(attempt=1, result="passed", summary="partial")],
        tests_run=[TestRunReport(command="pytest", exit_code=0, status="passed")],
        subagents=[],
        risks=[],
        trace_id="tr_test",
        semantic_validation=[{"valid": True}],
    )

    result = score_fixture_report(report, metadata)

    assert result["passed"] is True
    assert result["product_pass"] is True
    assert result["product_checks"]["final_tests_passed"] is True
    assert result["multi_file_contract"]["contract_matched"] is False
    assert result["oracle_diagnostics"]["minimum_changed_files"] is False


def test_fixture_report_scoring_records_two_file_contract_match() -> None:
    metadata = FixtureMetadata(
        name="contract",
        bug_shape="contract drift",
        goal="repair",
        expected_changed_source_files=[Path("pkg/a.py"), Path("pkg/b.py")],
        minimum_changed_files=2,
    )
    report = FinalReport(
        goal="repair",
        status="success",
        task_classification="source_fix",
        root_cause="contract drift",
        patch_plan={"summary": "complete"},
        changed_files=[
            ChangedFileReport(path=Path("pkg/a.py"), change_type="modify", justification="test"),
            ChangedFileReport(path=Path("pkg/b.py"), change_type="modify", justification="test"),
        ],
        attempts=[RepairAttemptReport(attempt=1, result="passed", summary="complete")],
        tests_run=[TestRunReport(command="pytest", exit_code=0, status="passed")],
        subagents=[],
        risks=[],
        trace_id="tr_test",
        semantic_validation=[{"valid": True}],
    )

    result = score_fixture_report(report, metadata)

    assert result["product_pass"] is True
    assert result["multi_file_contract"]["contract_matched"] is True


def test_v2_eval_missing_key_is_categorized(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    result = asyncio.run(run_suite("v2", Path(__file__).parents[1] / "fixtures", model_provider="openrouter"))

    assert result["passed"] is False
    assert result["fixture_count"] >= 10
    assert result["runtime_oracle_visible"] is False
    assert all(item["runtime_oracle_visible"] is False for item in result["results"])
    assert {item["failure_category"] for item in result["results"]} == {"missing_api_key"}


def test_v2_eval_progress_reports_status_without_stdout_json_side_effects(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    events = []

    result = asyncio.run(
        run_suite(
            "v2",
            Path(__file__).parents[1] / "fixtures" / "multifile-parser-validator",
            model_provider="openrouter",
            live_eval=True,
            progress=events.append,
        )
    )

    assert result["passed"] is False
    assert [event["event"] for event in events] == ["suite_started", "fixture_started", "fixture_completed", "suite_completed"]
    assert events[1]["fixture"] == "multifile-parser-validator"
    assert result["markdown_report_path"]
    assert Path(result["markdown_report_path"]).exists()
    text = Path(result["markdown_report_path"]).read_text(encoding="utf-8")
    assert "PatchPilot V2 Live Eval Report" in text
    assert "Product pass rate" in text
    assert "Multi-file contract match rate" in text
    assert "| Fixture | Product | Contract | Failure | Changed files | Trace | Report |" in text
    assert "multifile-parser-validator" in text
    assert "Changed files" in text
    assert "JSON report" in text
    assert "Model calls" in text
    assert "Cost" in text
    assert "Oracle diagnostics" in text


def test_runtime_progress_oserror_is_non_fatal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(
        Path(__file__).parents[1] / "fixtures" / "buggy-python-repo",
        repo,
        ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
    )
    config = PatchPilotConfig(repo=repo, allow_write=True, allow_exec=True, trace_dir=repo / ".patchpilot" / "traces")
    model_config = config.model_copy(update={"openrouter_api_key": "sk-test"})
    transport = SchemaAwareOpenRouterTransport(
        structured={
            "DiagnosisResult": [
                {
                    "root_cause": "add subtracts instead of adding",
                    "evidence": {},
                    "evidence_links": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                    "implicated_files": ["buggy_math/calculator.py"],
                    "shared_root_cause": "calculator implementation violates add contract",
                    "recommended_patch_direction": "return a + b",
                    "confidence": 0.9,
                    "risks": [],
                }
            ],
            "PatchPlan": [
                {
                    "task_classification": "source_fix",
                    "root_cause": "add subtracts instead of adding",
                    "evidence_refs": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                    "planned_changed_files": ["buggy_math/calculator.py"],
                    "edits": [
                        {
                            "path": "buggy_math/calculator.py",
                            "before": "return a - b",
                            "after": "return a + b",
                            "evidence_refs": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                            "purpose": "Repair add contract",
                            "expected_validation": ["pytest tests/test_calculator.py", "pytest"],
                            "root_cause_linkage": "same add contract",
                        }
                    ],
                    "patch": "",
                    "summary": "Return the sum from add.",
                }
            ],
            "ReviewResult": [
                {
                    "approved": True,
                    "issues": [],
                    "evidence": {},
                    "regression_risk": "low",
                    "missing_validation": [],
                    "changed_file_necessity": {"buggy_math/calculator.py": "contains add implementation"},
                    "blocking": False,
                    "confidence": 0.9,
                }
            ],
        }
    )
    model = OpenRouterModelClient(model_config, transport=transport)

    def broken_progress(payload: dict) -> None:
        raise OSError(22, "Invalid argument")

    report = asyncio.run(RepairRuntime(config, model, progress=broken_progress).run("repair failing pytest", "pytest"))

    assert report.status == "success"


def test_eval_work_copy_ignores_fixture_oracle_file() -> None:
    assert "fixture.json" in COPY_IGNORE_PATTERNS


def test_eval_work_copy_is_outside_fixture_ancestry() -> None:
    source = Path(__file__).parents[1] / "fixtures" / "mock-store-python"

    _, work_repo = _copy_fixture_to_work_repo(source, "smoke", "mock-store-python")

    assert "fixtures" not in work_repo.resolve().parts
    assert not (work_repo / "fixture.json").exists()
    assert _blind_work_repo_violations(work_repo) == []


def test_runtime_oracle_audit_detects_fixture_metadata_terms() -> None:
    report = FinalReport(
        goal=GENERIC_REPAIR_GOAL,
        status="failed",
        task_classification="source_fix",
        root_cause="unknown",
        patch_plan={"summary": "none"},
        changed_files=[],
        attempts=[],
        tests_run=[],
        subagents=[],
        risks=[],
        trace_id="tr_test",
    )
    events = [
        TraceEvent(
            trace_id="tr_test",
            session_id="s",
            event_type="tool.started",
            name="fs.read_file",
            payload={"input": {"path": "fixture.json"}},
        )
    ]

    audit = audit_runtime_oracle_visibility(events, report)

    assert audit["runtime_oracle_visible"] is True
    assert audit["violations"][0]["marker"] == "fixture.json"
