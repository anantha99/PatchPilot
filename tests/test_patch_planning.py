from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.runtime.graph import _has_patch_plan_evidence, _next_unread_source_path
from patchpilot.runtime.state import SessionState
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def _validate(repo: Path, payload: dict, config: PatchPilotConfig | None = None):
    context = ToolContext(repo_root=repo, config=config or PatchPilotConfig(repo=repo))
    return asyncio.run(ToolExecutor(build_registry()).execute("code.validate_patch_shape", payload, context))


def test_hybrid_patch_validation_rejects_structured_diff_file_mismatch(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py", "b.py"],
            "structured_edits": [
                {
                    "path": "a.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_a.py", "a.py"],
                    "root_cause_linkage": "same contract",
                }
            ],
            "evidence_refs": ["tests/test_a.py", "a.py"],
            "root_cause": "same contract",
            "patch": "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n",
        },
    )

    assert result.valid is False
    assert any("structured edits and unified diff" in reason for reason in result.reasons)


def test_semantic_validation_rejects_missing_evidence_links(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py"],
            "structured_edits": [{"path": "a.py", "before": "value = 1", "after": "value = 2"}],
            "patch": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n",
        },
    )

    assert result.valid is False
    assert any("evidence" in reason for reason in result.semantic_reasons)


def test_hybrid_patch_validation_reports_escaped_structured_edit_path(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py"],
            "structured_edits": [{"path": "../outside.py", "before": "value = 1", "after": "value = 2"}],
            "evidence_refs": ["tests/test_a.py", "a.py"],
            "root_cause": "contract",
            "patch": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n",
        },
    )

    assert result.valid is False
    assert any("path escapes repo" in reason for reason in result.reasons)


def test_semantic_validation_accepts_multifile_source_fix_with_shared_root_cause(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py", "b.py"],
            "structured_edits": [
                {
                    "path": "a.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_contract.py", "a.py"],
                    "root_cause_linkage": "same contract",
                },
                {
                    "path": "b.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_contract.py", "b.py"],
                    "root_cause_linkage": "same contract",
                },
            ],
            "evidence_refs": ["tests/test_contract.py", "a.py", "b.py"],
            "root_cause": "shared contract drift",
            "patch": (
                "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
                "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
            ),
        },
    )

    assert result.valid is True
    assert [path.as_posix() for path in result.changed_files] == ["a.py", "b.py"]


def test_semantic_validation_accepts_structured_search_replace_without_diff(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py"],
            "structured_edits": [
                {
                    "path": "a.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_a.py", "a.py"],
                    "root_cause_linkage": "same contract",
                }
            ],
            "evidence_refs": ["tests/test_a.py", "a.py"],
            "root_cause": "shared contract drift",
        },
    )

    assert result.valid is True
    assert [path.as_posix() for path in result.changed_files] == ["a.py"]
    assert result.diff_lines == 0


def test_patch_validation_rejects_model_inferred_target_without_concrete_edit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("value = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py", "b.py"],
            "structured_edits": [
                {
                    "path": "a.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_contract.py", "a.py"],
                    "root_cause_linkage": "same contract",
                }
            ],
            "evidence_refs": ["tests/test_contract.py", "a.py"],
            "root_cause": "shared contract drift",
        },
    )

    assert result.valid is False
    assert any("target file lacks concrete edit: b.py" in reason for reason in result.reasons)


def test_patch_validation_rejects_ambiguous_structured_search(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")

    result = _validate(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["a.py"],
            "structured_edits": [
                {
                    "path": "a.py",
                    "before": "value = 1",
                    "after": "value = 2",
                    "evidence_refs": ["tests/test_contract.py", "a.py"],
                    "root_cause_linkage": "same contract",
                }
            ],
            "evidence_refs": ["tests/test_contract.py", "a.py"],
            "root_cause": "shared contract drift",
        },
    )

    assert result.valid is False
    assert any("ambiguous structured edit SEARCH text" in reason for reason in result.reasons)


def test_patchpilot_config_has_no_fixture_oracle_fields(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path)

    assert not hasattr(config, "expected_changed_files")
    assert not hasattr(config, "allowed_changed_files")
    assert not hasattr(config, "minimum_changed_files")


def test_patch_planning_waits_for_all_implicated_source_files(tmp_path: Path) -> None:
    package = tmp_path / "calendar_rules"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "window.py").write_text("from .constants import WEEKEND\n", encoding="utf-8")
    (package / "constants.py").write_text("WEEKEND = {5}\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_calendar_rules.py").write_text("from calendar_rules import can_book\n", encoding="utf-8")
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    state = SessionState(repo=tmp_path, goal="repair calendar")
    state.phase = "plan_patch"
    state.tool_history.append({"tool_name": "session.mark_phase", "output": {"text": "plan_patch"}})
    state.working_set.implicated_sources = [Path("calendar_rules/window.py"), Path("calendar_rules/constants.py")]
    state.working_set.source_candidates["tests/test_calendar_rules.py"] = [Path("calendar_rules/__init__.py")]
    context.artifacts["subagents"] = [
        {
            "kind": "diagnosis",
            "result": {"implicated_files": ["calendar_rules/window.py", "calendar_rules/constants.py"]},
        }
    ]

    assert _next_unread_source_path(state, context) == "calendar_rules/window.py"

    state.tool_history.append(
        {
            "tool_name": "fs.read_file",
            "output": {"path": "calendar_rules/window.py", "content": "from .constants import WEEKEND\n"},
        }
    )
    files = [
        {"path": "tests/test_calendar_rules.py", "content": "from calendar_rules import can_book\n"},
        {"path": "calendar_rules/window.py", "content": "from .constants import WEEKEND\n"},
    ]

    assert _next_unread_source_path(state, context) == "calendar_rules/constants.py"
    assert _has_patch_plan_evidence(files, context, state) is False

    files.append({"path": "calendar_rules/constants.py", "content": "WEEKEND = {5}\n"})

    assert _has_patch_plan_evidence(files, context, state) is True
