from pathlib import Path
import asyncio

import pytest

from patchpilot.config import PatchPilotConfig
from patchpilot.errors import PolicyError
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def test_write_tools_require_allow_write(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path, allow_write=False)
    executor = ToolExecutor(build_registry())
    context = ToolContext(repo_root=tmp_path, config=config)

    with pytest.raises(PolicyError):
        asyncio.run(executor.execute("fs.write_file", {"path": "x.txt", "content": "x"}, context))


def test_exec_tools_require_allow_exec(tmp_path: Path) -> None:
    config = PatchPilotConfig(repo=tmp_path, allow_exec=False)
    executor = ToolExecutor(build_registry())
    context = ToolContext(repo_root=tmp_path, config=config)

    with pytest.raises(PolicyError):
        asyncio.run(executor.execute("exec.run_command", {"command": "python --version"}, context))
