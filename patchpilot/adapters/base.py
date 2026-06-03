"""Stack adapter contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class StackAdapter(Protocol):
    def applies_to(self, repo: Path, test_command: str | None = None) -> bool: ...
    def detect_test_command(self, repo: Path, supplied: str | None = None) -> str | None: ...
    def targeted_command(self, failure_output: str) -> str | None: ...
