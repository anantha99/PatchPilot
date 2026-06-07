from pathlib import Path
import asyncio

import pytest

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import PolicyError
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def _apply_patch(repo: Path, patch: str, structured_edits: list[dict] | None = None):
    config = PatchPilotConfig(repo=repo, allow_write=True)
    context = ToolContext(repo_root=repo, config=config)
    payload = {"patch": patch}
    if structured_edits is not None:
        payload["structured_edits"] = structured_edits
    return asyncio.run(ToolExecutor(build_registry()).execute("fs.apply_patch", payload, context))


def _validate_patch(repo: Path, payload: dict):
    config = PatchPilotConfig(repo=repo)
    context = ToolContext(repo_root=repo, config=config)
    return asyncio.run(ToolExecutor(build_registry()).execute("code.validate_patch_shape", payload, context))


def _read_files(repo: Path, payload: dict):
    config = PatchPilotConfig(repo=repo)
    context = ToolContext(repo_root=repo, config=config)
    return asyncio.run(ToolExecutor(build_registry()).execute("fs.read_files", payload, context))


def test_read_files_returns_partial_results_for_missing_paths(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("value = 1\n", encoding="utf-8")

    result = _read_files(tmp_path, {"paths": ["ok.py", "missing.py"]})

    assert [item.path for item in result.files] == [Path("ok.py")]
    assert result.files[0].content.replace("\r\n", "\n") == "value = 1\n"
    assert result.missing_files == [Path("missing.py")]
    assert result.errors[0].path == Path("missing.py")
    assert result.errors[0].error_type == "FileNotFoundError"


def test_read_files_reports_repo_escape_as_per_path_error(tmp_path: Path) -> None:
    result = _read_files(tmp_path, {"paths": ["../outside.py"]})

    assert result.files == []
    assert result.missing_files == []
    assert result.errors[0].path == Path("../outside.py")
    assert result.errors[0].error_type == "PolicyError"
    assert "escapes repository" in result.errors[0].error


def test_apply_patch_fallback_applies_simple_unified_diff(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")

    result = _apply_patch(
        tmp_path,
        "diff --git a/sample.py b/sample.py\n"
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n",
    )

    assert result.applied is True
    assert target.read_text(encoding="utf-8") == "value = 2\n"


def test_git_diff_uses_applied_patch_artifact_outside_git_repo(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path, allow_write=True))
    executor = ToolExecutor(build_registry())

    asyncio.run(
        executor.execute(
            "fs.apply_patch",
            {
                "patch": (
                    "diff --git a/sample.py b/sample.py\n"
                    "--- a/sample.py\n"
                    "+++ b/sample.py\n"
                    "@@ -1 +1 @@\n"
                    "-value = 1\n"
                    "+value = 2\n"
                )
            },
            context,
        )
    )
    diff = asyncio.run(executor.execute("git.diff", {}, context))

    assert diff.exit_code == 0
    assert "+value = 2" in diff.stdout


def test_apply_patch_fallback_reports_no_change_when_target_text_absent(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")

    result = _apply_patch(
        tmp_path,
        "diff --git a/sample.py b/sample.py\n"
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1 +1 @@\n"
        "-missing = 1\n"
        "+missing = 2\n",
    )

    assert result.applied is False
    assert target.read_text(encoding="utf-8") == "value = 1\n"


def test_apply_patch_uses_structured_edits_when_diff_hunk_is_malformed(tmp_path: Path) -> None:
    package = tmp_path / "calendar_rules"
    package.mkdir()
    (package / "constants.py").write_text("WEEKEND_DAYS = {5}\nMAX_BOOKING_DAYS = 30\n", encoding="utf-8")
    (package / "window.py").write_text(
        "from .constants import MAX_BOOKING_DAYS, WEEKEND_DAYS\n\n\n"
        "def can_book(days_from_now: int, weekday: int) -> bool:\n"
        "    if weekday in WEEKEND_DAYS:\n"
        "        return False\n"
        "    return 0 <= days_from_now < MAX_BOOKING_DAYS\n",
        encoding="utf-8",
    )

    result = _apply_patch(
        tmp_path,
        "diff --git a/calendar_rules/constants.py b/calendar_rules/constants.py\n"
        "--- a/calendar_rules/constants.py\n"
        "+++ b/calendar_rules/constants.py\n"
        "@@ -1,99 +1,99 @@\n"
        "-WEEKEND_DAYZ = {5}\n"
        "+WEEKEND_DAYS = {5, 6}\n"
        " MAX_BOOKING_DAYS = 30\n"
        "diff --git a/calendar_rules/window.py b/calendar_rules/window.py\n"
        "--- a/calendar_rules/window.py\n"
        "+++ b/calendar_rules/window.py\n"
        "@@ -5,99 +5,99 @@\n"
        "     if weekday in WEEKEND_DAYS:\n"
        "         return False\n"
        "-    return 0 <= days_from_now < MAX_BOOKING_DAYS\n"
        "+    return 0 <= days_from_now <= MAX_BOOKING_DAYS\n",
        [
            {
                "path": "calendar_rules/constants.py",
                "before": "WEEKEND_DAYS = {5}",
                "after": "WEEKEND_DAYS = {5, 6}",
            },
            {
                "path": "calendar_rules/window.py",
                "before": "    return 0 <= days_from_now < MAX_BOOKING_DAYS",
                "after": "    return 0 <= days_from_now <= MAX_BOOKING_DAYS",
            },
        ],
    )

    assert result.applied is True
    assert "diff --git" not in result.clean_diff
    assert "--- a/calendar_rules/constants.py" in result.clean_diff
    assert "WEEKEND_DAYS = {5, 6}" in (package / "constants.py").read_text(encoding="utf-8")
    assert "0 <= days_from_now <= MAX_BOOKING_DAYS" in (package / "window.py").read_text(encoding="utf-8")


def test_apply_patch_accepts_structured_edits_without_model_diff(tmp_path: Path) -> None:
    target = tmp_path / "sample.py"
    target.write_text("value = 1\n", encoding="utf-8")
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path, allow_write=True))
    executor = ToolExecutor(build_registry())

    result = asyncio.run(
        executor.execute(
            "fs.apply_patch",
            {
                "structured_edits": [
                    {
                        "path": "sample.py",
                        "before": "value = 1",
                        "after": "value = 2",
                    }
                ]
            },
            context,
        )
    )
    diff = asyncio.run(executor.execute("git.diff", {}, context))

    assert result.applied is True
    assert result.changed_files == [Path("sample.py")]
    assert "value = 2" in target.read_text(encoding="utf-8")
    assert "+value = 2" in result.clean_diff
    assert diff.exit_code == 0
    assert "+value = 2" in diff.stdout


def test_apply_patch_rejects_paths_that_escape_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("old\n", encoding="utf-8")

    with pytest.raises(PolicyError):
        _apply_patch(
            tmp_path,
            "diff --git a/../outside.txt b/../outside.txt\n"
            "--- a/../outside.txt\n"
            "+++ b/../outside.txt\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n",
        )

    assert outside.read_text(encoding="utf-8") == "old\n"


def test_validate_patch_shape_rejects_protected_and_undeclared_paths(tmp_path: Path) -> None:
    result = _validate_patch(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["src/app.py"],
            "patch": "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+new\n",
        },
    )

    assert result.valid is False
    assert any("protected path" in reason for reason in result.reasons)
    assert any("undeclared file" in reason for reason in result.reasons)


def test_validate_patch_shape_enforces_diff_limit_and_test_only_guard(tmp_path: Path) -> None:
    patch = (
        "diff --git a/tests/test_app.py b/tests/test_app.py\n"
        "--- a/tests/test_app.py\n"
        "+++ b/tests/test_app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )

    result = _validate_patch(
        tmp_path,
        {
            "task_classification": "source_fix",
            "target_files": ["tests/test_app.py"],
            "patch": patch,
            "max_diff_lines": 1,
        },
    )

    assert result.valid is False
    assert any("diff too large" in reason for reason in result.reasons)
    assert any("test-only patch" in reason for reason in result.reasons)
