"""Execution-tool tests for permissions, risk policy, and command capture."""

from pathlib import Path
import asyncio

import pytest

from patchpilot.errors import PolicyError
from patchpilot.schemas.common import CommandRisk
from patchpilot.config import PatchPilotConfig
from patchpilot.tools import build_registry
from patchpilot.tools.exec_tools import _normalize_command
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.helpers import classify_command_risk, run_process
from patchpilot.tools.registry import ToolContext


def test_command_risk_classification() -> None:
    assert classify_command_risk("pytest") == CommandRisk.LOW
    assert classify_command_risk("git reset --hard") == CommandRisk.MEDIUM
    assert classify_command_risk("rm -rf .") == CommandRisk.HIGH
    assert classify_command_risk("python -c \"import shutil; shutil.rmtree('.git')\"") == CommandRisk.HIGH


def test_pytest_normalization_can_disable_capture_for_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATCHPILOT_PYTEST_NO_CAPTURE", "1")

    assert " -m pytest --capture=no" in _normalize_command("pytest")
    assert _normalize_command("pytest tests/test_example.py").endswith(
        " -m pytest --capture=no tests/test_example.py"
    )
    assert _normalize_command("pytest -s tests/test_example.py").endswith(" -m pytest -s tests/test_example.py")


def test_high_risk_command_requires_high_risk_flag(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        asyncio.run(run_process(tmp_path, "python --version", 5, CommandRisk.HIGH))


def test_command_arguments_cannot_downgrade_classified_risk(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path, allow_exec=True, allow_high_risk_exec=False)
    context = ToolContext(repo_root=tmp_path, config=config)

    with pytest.raises(PolicyError):
        asyncio.run(
            ToolExecutor(build_registry()).execute(
                "exec.run_command",
                {
                    "command": "python -c \"import shutil; shutil.rmtree('.git')\"",
                    "risk": "medium",
                },
                context,
            )
        )


def test_blind_eval_test_tool_rejects_parent_metadata_read(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path, allow_exec=True, blind_eval=True)
    context = ToolContext(repo_root=tmp_path, config=config)

    with pytest.raises(PolicyError):
        asyncio.run(
            ToolExecutor(build_registry()).execute(
                "exec.run_tests",
                {"command": r"cmd /c type ..\fixture.json"},
                context,
            )
        )


def test_blind_eval_test_tool_allows_pytest_targets(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path, allow_exec=True, blind_eval=True)
    context = ToolContext(repo_root=tmp_path, config=config)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = asyncio.run(
        ToolExecutor(build_registry()).execute(
            "exec.run_targeted_tests",
            {"command": "pytest tests/test_ok.py"},
            context,
        )
    )

    assert result.exit_code == 0
