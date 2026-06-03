"""Generic supplied-command adapter."""

from __future__ import annotations

from pathlib import Path


class GenericCommandAdapter:
    def applies_to(self, repo: Path, test_command: str | None = None) -> bool:
        return bool(test_command)

    def detect_test_command(self, repo: Path, supplied: str | None = None) -> str | None:
        return supplied

    def targeted_command(self, failure_output: str) -> str | None:
        return None
