"""Shared schema primitives for paths, permissions, tools, and text outputs."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Permission(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"
    EXTERNAL = "external"


class ToolNamespace(StrEnum):
    FS = "fs"
    GIT = "git"
    CODE = "code"
    EXEC = "exec"
    SESSION = "session"
    SUBAGENT = "subagent"


class CommandRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class EmptyInput(BaseModel):
    pass


class EmptyOutput(BaseModel):
    ok: bool = True


class PathInput(BaseModel):
    path: Path


class PathsInput(BaseModel):
    paths: list[Path]


class TextOutput(BaseModel):
    text: str


class JsonObject(BaseModel):
    data: dict[str, Any]


class FileContent(BaseModel):
    path: Path
    content: str


class FileReadError(BaseModel):
    path: Path
    error_type: str
    error: str


class FileBundle(BaseModel):
    files: list[FileContent]
    missing_files: list[Path] = Field(default_factory=list)
    errors: list[FileReadError] = Field(default_factory=list)


class SearchResult(BaseModel):
    file_path: Path
    line: int
    snippet: str


class SearchResults(BaseModel):
    results: list[SearchResult] = Field(default_factory=list)
