from pathlib import Path

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
