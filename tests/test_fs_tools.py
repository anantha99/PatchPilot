from pathlib import Path
import asyncio

import pytest

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import PolicyError
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def _apply_patch(repo: Path, patch: str):
    config = PatchPilotConfig(repo=repo, allow_write=True)
    context = ToolContext(repo_root=repo, config=config)
    return asyncio.run(ToolExecutor(build_registry()).execute("fs.apply_patch", {"patch": patch}, context))


def _validate_patch(repo: Path, payload: dict):
    config = PatchPilotConfig(repo=repo)
    context = ToolContext(repo_root=repo, config=config)
    return asyncio.run(ToolExecutor(build_registry()).execute("code.validate_patch_shape", payload, context))


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
