from pathlib import Path
import asyncio
import shutil

import pytest

from patchpilot.config import PatchPilotConfig
from patchpilot.evals.suites import run_suite
from patchpilot.evals.harness import COPY_IGNORE_PATTERNS, FixtureMetadata, discover_multifile_fixtures, score_fixture_report, score_trace
from patchpilot.models.fake import FakeModelClient
from patchpilot.runtime.graph import RepairRuntime
from patchpilot.schemas.reports import ChangedFileReport, FinalReport, RepairAttemptReport, TestRunReport, TraceEvent


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


def test_multifile_fixture_metadata_is_discoverable_and_source_only() -> None:
    fixtures = discover_multifile_fixtures(Path(__file__).parents[1] / "fixtures")

    assert len(fixtures) >= 10
    assert all((fixture / "fixture.json").exists() for fixture in fixtures)


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

    def broken_progress(payload: dict) -> None:
        raise OSError(22, "Invalid argument")

    report = asyncio.run(RepairRuntime(config, FakeModelClient(), progress=broken_progress).run("repair failing pytest", "pytest"))

    assert report.status == "success"


def test_eval_work_copy_ignores_fixture_oracle_file() -> None:
    assert "fixture.json" in COPY_IGNORE_PATTERNS
