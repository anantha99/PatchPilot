from pathlib import Path
import asyncio

import pytest

from patchpilot.errors import PolicyError
from patchpilot.schemas.common import CommandRisk
from patchpilot.config import PatchPilotConfig
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.helpers import classify_command_risk, run_process
from patchpilot.tools.registry import ToolContext


def test_command_risk_classification() -> None:
    assert classify_command_risk("pytest") == CommandRisk.LOW
    assert classify_command_risk("git reset --hard") == CommandRisk.MEDIUM
    assert classify_command_risk("rm -rf .") == CommandRisk.HIGH
    assert classify_command_risk("python -c \"import shutil; shutil.rmtree('.git')\"") == CommandRisk.HIGH


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
