from pathlib import Path
import asyncio
import shutil

from patchpilot.evals.harness import run_smoke_eval


COPY_IGNORE = shutil.ignore_patterns(".patchpilot", ".pytest_cache", "__pycache__")


def test_smoke_eval_passes_on_fixture_copy(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "fixtures" / "buggy-python-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)

    result = asyncio.run(run_smoke_eval(repo, model_provider="fake"))

    assert result["passed"] is True
    assert result["checks"]["tools_50_plus"] is True
    assert result["checks"]["tool_calls_20_plus"] is True
