from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def test_memory_tools_store_and_retrieve_artifacts(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    executor = ToolExecutor(build_registry())

    asyncio.run(executor.execute("memory_eval.store_artifact", {"key": "answer", "value": {"ok": True}}, context))
    output = asyncio.run(executor.execute("memory_eval.retrieve_artifacts", {"keys": ["answer"]}, context))

    assert output.artifacts["answer"] == {"ok": True}
