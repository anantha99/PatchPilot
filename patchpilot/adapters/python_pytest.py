"""Python pytest adapter."""

from __future__ import annotations

import re
from pathlib import Path


class PythonPytestAdapter:
    def applies_to(self, repo: Path, test_command: str | None = None) -> bool:
        return bool((repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists() or list(repo.glob("tests/test_*.py")))

    def detect_test_command(self, repo: Path, supplied: str | None = None) -> str | None:
        return supplied or "pytest" if self.applies_to(repo, supplied) else None

    def targeted_command(self, failure_output: str) -> str | None:
        match = re.search(r"(tests[/\\][A-Za-z0-9_./\\-]+\.py)", failure_output)
        return f"pytest {match.group(1)}" if match else None
