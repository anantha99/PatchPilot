"""Shared helpers for local repo tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from patchpilot.errors import ExecutionTimeoutError, PolicyError, ToolError
from patchpilot.schemas.common import CommandRisk
from patchpilot.schemas.tool_io import CommandOutput


def repo_path(repo_root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    resolved = candidate.resolve()
    root = repo_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise PolicyError(f"Path escapes repository: {path}")
    return resolved


def rel_path(repo_root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return path


def read_text(path: Path, max_bytes: int | None = None) -> str:
    data = path.read_bytes()
    if max_bytes is not None:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_temp_file(repo_root: Path, prefix: str, suffix: str, content: str) -> Path:
    tmp_dir = repo_root / ".patchpilot" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        encoding="utf-8",
        prefix=prefix,
        suffix=suffix,
        dir=tmp_dir,
    )
    with handle:
        handle.write(content)
    return Path(handle.name)


async def run_process(
    repo_root: Path,
    command: str,
    timeout_seconds: int,
    risk: CommandRisk,
) -> CommandOutput:
    start = time.perf_counter()
    if risk == CommandRisk.HIGH:
        raise PolicyError("High-risk command execution requires explicit high-risk handling")
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ExecutionTimeoutError(f"Command timed out: {command}") from exc
    return CommandOutput(
        command=command,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        exit_code=process.returncode or 0,
        duration_ms=int((time.perf_counter() - start) * 1000),
        risk=risk,
    )


def grep_text(root: Path, query: str, max_results: int) -> list[tuple[Path, int, str]]:
    results: list[tuple[Path, int, str]] = []
    for path in root.rglob("*"):
        if len(results) >= max_results:
            break
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query in line:
                    results.append((path, line_no, line.strip()))
                    if len(results) >= max_results:
                        break
        except OSError:
            continue
    return results


def grep_regex(root: Path, pattern: str, max_results: int) -> list[tuple[Path, int, str]]:
    regex = re.compile(pattern)
    results: list[tuple[Path, int, str]] = []
    for path in root.rglob("*"):
        if len(results) >= max_results:
            break
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    results.append((path, line_no, line.strip()))
                    if len(results) >= max_results:
                        break
        except OSError:
            continue
    return results


def detect_test_command(root: Path) -> str | None:
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        return "pytest"
    if (root / "package.json").exists():
        return "npm test"
    if (root / "go.mod").exists():
        return "go test ./..."
    return None

