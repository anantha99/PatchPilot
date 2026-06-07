from pathlib import Path
import asyncio

from patchpilot.config import PatchPilotConfig
from patchpilot.tools import build_registry
from patchpilot.tools.executor import ToolExecutor
from patchpilot.tools.registry import ToolContext


def test_session_tools_store_and_retrieve_artifacts(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    executor = ToolExecutor(build_registry())

    asyncio.run(executor.execute("session.store_artifact", {"key": "answer", "value": {"ok": True}}, context))
    output = asyncio.run(executor.execute("session.retrieve_artifacts", {"keys": ["answer"]}, context))

    assert output.artifacts["answer"] == {"ok": True}


def test_session_tools_sanitize_runtime_artifacts(tmp_path: Path) -> None:
    context = ToolContext(repo_root=tmp_path, config=PatchPilotConfig(repo=tmp_path))
    context.artifacts["subagent_runtime"] = object()
    context.artifacts["nested"] = {"child_runtime": object(), "value": 1}
    executor = ToolExecutor(build_registry())

    output = asyncio.run(executor.execute("session.retrieve_artifacts", {}, context))

    assert "subagent_runtime" not in output.artifacts
    assert "child_runtime" not in output.artifacts["nested"]
    assert output.artifacts["nested"]["value"] == 1


def test_fixture_metadata_loader_is_not_registered_in_product_tools() -> None:
    registry = build_registry()

    assert "memory_eval.load_fixture_metadata" not in {tool.name for tool in registry.list()}
    assert all(not tool.name.startswith("memory_eval.") for tool in registry.list())
