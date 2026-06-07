"""Integration coverage for smoke eval report and trace proof."""

from pathlib import Path
import asyncio
import shutil

from patchpilot.evals.harness import run_smoke_eval
from tests.support.openrouter_mock import SchemaAwareOpenRouterTransport


COPY_IGNORE = shutil.ignore_patterns(".patchpilot", ".pytest_cache", "__pycache__")


def test_smoke_eval_passes_on_fixture_copy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    source = Path(__file__).parents[2] / "fixtures" / "buggy-python-repo"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo, ignore=COPY_IGNORE)
    transport = SchemaAwareOpenRouterTransport(
        structured={
            "DiagnosisResult": [
                {
                    "root_cause": "add subtracts instead of adding",
                    "evidence": {"test": "calculator test", "source": "calculator implementation"},
                    "evidence_links": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                    "implicated_files": ["buggy_math/calculator.py"],
                    "shared_root_cause": "calculator implementation violates add contract",
                    "recommended_patch_direction": "return a + b",
                    "confidence": 0.9,
                    "risks": [],
                }
            ],
            "PatchPlan": [
                {
                    "task_classification": "source_fix",
                    "root_cause": "add subtracts instead of adding",
                    "evidence_refs": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                    "planned_changed_files": ["buggy_math/calculator.py"],
                    "edits": [
                        {
                            "path": "buggy_math/calculator.py",
                            "before": "return a - b",
                            "after": "return a + b",
                            "evidence_refs": ["tests/test_calculator.py", "buggy_math/calculator.py"],
                            "purpose": "Repair add contract",
                            "expected_validation": ["pytest tests/test_calculator.py", "pytest"],
                            "root_cause_linkage": "same add contract",
                        }
                    ],
                    "patch": "",
                    "summary": "Return the sum from add.",
                }
            ],
            "ReviewResult": [
                {
                    "approved": True,
                    "issues": [],
                    "evidence": {},
                    "regression_risk": "low",
                    "missing_validation": [],
                    "changed_file_necessity": {"buggy_math/calculator.py": "contains add implementation"},
                    "blocking": False,
                    "confidence": 0.9,
                }
            ],
        }
    )

    result = asyncio.run(run_smoke_eval(repo, model_transport=transport))

    assert result["passed"] is True
    assert result["checks"]["tools_50_plus"] is True
    assert result["checks"]["tool_calls_20_plus"] is True
