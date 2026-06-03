from pathlib import Path
import asyncio

import pytest

from patchpilot.errors import PolicyError
from patchpilot.schemas.common import CommandRisk
from patchpilot.tools.helpers import classify_command_risk, run_process


def test_command_risk_classification() -> None:
    assert classify_command_risk("pytest") == CommandRisk.LOW
    assert classify_command_risk("git reset --hard") == CommandRisk.MEDIUM
    assert classify_command_risk("rm -rf .") == CommandRisk.HIGH


def test_high_risk_command_requires_high_risk_flag(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        asyncio.run(run_process(tmp_path, "python --version", 5, CommandRisk.HIGH))
