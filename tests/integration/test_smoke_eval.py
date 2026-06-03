from pathlib import Path
import asyncio
import shutil

from patchpilot.evals.harness import run_smoke_eval


def test_smoke_eval_passes_on_fixture_copy(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "buggy-python-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)

    result = asyncio.run(run_smoke_eval(repo))

    assert result["passed"] is True
    assert result["checks"]["tools_50_plus"] is True
    assert result["checks"]["tool_calls_20_plus"] is True
