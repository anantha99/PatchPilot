"""Python pytest adapter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PythonPytestAdapter:
    def applies_to(self, repo: Path, test_command: str | None = None) -> bool:
        return bool((repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists() or list(repo.glob("tests/test_*.py")))

    def detect_test_command(self, repo: Path, supplied: str | None = None) -> str | None:
        return supplied or "pytest" if self.applies_to(repo, supplied) else None

    def targeted_command(self, failure_output: str) -> str | None:
        match = re.search(r"(tests[/\\][A-Za-z0-9_./\\-]+\.py)", failure_output)
        return f"pytest {match.group(1)}" if match else None

    def failure_locations(self, failure_output: str) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        patterns = [
            r"(?P<file>[A-Za-z0-9_./\\-]+\.py):(?P<line>\d+):\s*(?P<test>test_[A-Za-z0-9_]+)?",
            r"FAILED\s+(?P<file>[A-Za-z0-9_./\\-]+\.py)::(?P<test>\S+)",
            r'File "(?P<file>[^"]+\.py)", line (?P<line>\d+)',
        ]
        seen: set[tuple[str, int | None, str | None]] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, failure_output):
                file_path = match.group("file").replace("\\", "/")
                line = int(match.groupdict().get("line") or 0) or None
                test_name = match.groupdict().get("test")
                key = (file_path, line, test_name)
                if key in seen:
                    continue
                seen.add(key)
                locations.append({"file": file_path, "line": line, "test": test_name})
        return locations

    def source_candidates_for_test(self, repo: Path, test_path: Path) -> list[Path]:
        test_file = repo / test_path
        candidates: list[Path] = []
        if not test_file.exists():
            return candidates
        text = test_file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"from\s+([A-Za-z0-9_.]+)\s+import|import\s+([A-Za-z0-9_.]+)", text):
            module = next(group for group in match.groups() if group)
            parts = module.split(".")
            candidate = repo.joinpath(*parts).with_suffix(".py")
            package_candidate = repo.joinpath(*parts, "__init__.py")
            for path in (candidate, package_candidate):
                if path.exists():
                    candidates.append(path.relative_to(repo))
                    if path.name == "__init__.py":
                        candidates.extend(_reexport_candidates(repo, path, text))
        if not candidates and test_path.name.startswith("test_"):
            stem = test_path.stem.removeprefix("test_")
            candidates.extend(path.relative_to(repo) for path in repo.rglob(f"{stem}.py") if "tests" not in path.parts)
        return list(dict.fromkeys(candidates))


def _reexport_candidates(repo: Path, package_init: Path, test_text: str) -> list[Path]:
    package_text = package_init.read_text(encoding="utf-8", errors="replace")
    candidates: list[Path] = []
    imported_names = set(re.findall(r"^from\s+[A-Za-z0-9_.]+\s+import\s+([A-Za-z0-9_, ]+)$", test_text, re.MULTILINE))
    imported_text = ",".join(imported_names)
    for match in re.finditer(r"^from\s+\.([A-Za-z0-9_]+)\s+import\s+([A-Za-z0-9_, ]+)$", package_text, re.MULTILINE):
        module, names = match.groups()
        if imported_text and not any(name.strip() in imported_text for name in names.split(",")):
            continue
        path = package_init.parent / f"{module}.py"
        if path.exists():
            candidates.append(path.relative_to(repo))
    return candidates
