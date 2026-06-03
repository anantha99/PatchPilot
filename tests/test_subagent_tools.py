from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def test_subagent_tool_returns_valid_shape(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    executor = ToolExecutor(build_registry())

    output = asyncio.run(
        executor.execute(
            "subagent.spawn_diagnosis",
            {"task": "diagnose", "context": {"output": "failure"}},
            context,
        )
    )

    assert output.name == "diagnosis"
    assert output.status == "success"
    assert output.result["scoped"] is True
