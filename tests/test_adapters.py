from pathlib import Path
import subprocess
import sys

from patchpilot.adapters import GenericCommandAdapter, PythonPytestAdapter


def test_python_pytest_adapter_detects_pytest_repo(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    adapter = PythonPytestAdapter()

    assert adapter.applies_to(tmp_path)
    assert adapter.detect_test_command(tmp_path) == "pytest"


def test_generic_adapter_requires_supplied_command(tmp_path: Path) -> None:
    adapter = GenericCommandAdapter()

    assert not adapter.applies_to(tmp_path)
    assert adapter.applies_to(tmp_path, "make test")
    assert adapter.detect_test_command(tmp_path, "make test") == "make test"


def test_python_pytest_adapter_extracts_parametrized_failure_locations() -> None:
    output = """
FAILED tests/test_parser.py::test_parse_comma_pair[name,email-expected0] - ValueError
tests/test_parser.py:12: AssertionError
  File "csv_tools/parser.py", line 2, in parse_pair
"""
    adapter = PythonPytestAdapter()

    locations = adapter.failure_locations(output)

    assert {"file": "tests/test_parser.py", "line": None, "test": "test_parse_comma_pair[name,email-expected0]"} in locations
    assert {"file": "tests/test_parser.py", "line": 12, "test": None} in locations
    assert {"file": "csv_tools/parser.py", "line": 2, "test": None} in locations


def test_python_pytest_adapter_maps_test_imports_to_source() -> None:
    repo = Path(__file__).parents[1] / "fixtures" / "buggy-parser-repo"
    adapter = PythonPytestAdapter()

    candidates = adapter.source_candidates_for_test(repo, Path("tests/test_parser.py"))

    assert Path("csv_tools/parser.py") in candidates


def test_additional_python_fixtures_fail_before_repair() -> None:
    root = Path(__file__).parents[1] / "fixtures"

    for fixture in ("buggy-validation-repo", "buggy-parser-repo", "mock-store-python"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=root / fixture,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        assert result.returncode != 0, result.stdout + result.stderr
