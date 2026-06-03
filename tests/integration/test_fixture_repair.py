from pathlib import Path
import asyncio
import shutil

from patchpilot.config import PatchPilotConfig
from patchpilot.models.fake import FakeModelClient
from patchpilot.runtime.graph import RepairRuntime


def test_fixture_repair_produces_success_report(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "buggy-python-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)
    config = PatchPilotConfig(repo=repo, trace_dir=tmp_path / "traces", allow_write=True, allow_exec=True)

    report = asyncio.run(RepairRuntime(config, FakeModelClient()).run("repair failing pytest", "pytest"))

    assert report.status == "success"
    assert report.trace_id
    assert report.subagents
    assert (repo / "buggy_math" / "calculator.py").read_text(encoding="utf-8").strip().endswith("return a + b")
