from patchpilot.evals.harness import score_trace
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
