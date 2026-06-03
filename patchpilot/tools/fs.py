"""Filesystem tools."""

from __future__ import annotations

import re
from pathlib import Path

from patchpilot.schemas.common import CommandRisk, FileBundle, FileContent, JsonObject, PathInput, Permission, ToolNamespace
from patchpilot.schemas.tool_io import (
    ApplyPatchInput,
    ApplyPatchOutput,
    FileExistsOutput,
    GlobInput,
    GlobOutput,
    HashFileOutput,
    ListDirInput,
    ListDirOutput,
    ReadFileInput,
    ReadFilesInput,
    StatFileOutput,
    TempFileInput,
    TempFileOutput,
    WriteFileInput,
)
from patchpilot.tools.helpers import create_temp_file, read_json_file, read_text, rel_path, repo_path, run_process, sha256_file, write_json_file
from patchpilot.tools.registry import ToolContext, ToolRegistry


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="fs.list_dir",
        namespace=ToolNamespace.FS,
        description="List entries in a repository directory.",
        input_schema=ListDirInput,
        output_schema=ListDirOutput,
        permission=Permission.READ,
    )
    async def list_dir(input: ListDirInput, context: ToolContext) -> ListDirOutput:
        path = repo_path(Path(context.repo_root), input.path)
        return ListDirOutput(entries=sorted(child.name for child in path.iterdir()))

    @registry.tool(
        name="fs.read_file",
        namespace=ToolNamespace.FS,
        description="Read a UTF-8 text file from the repository.",
        input_schema=ReadFileInput,
        output_schema=FileContent,
        permission=Permission.READ,
    )
    async def read_file(input: ReadFileInput, context: ToolContext) -> FileContent:
        path = repo_path(Path(context.repo_root), input.path)
        return FileContent(path=rel_path(Path(context.repo_root), path), content=read_text(path, input.max_bytes))

    @registry.tool(
        name="fs.read_files",
        namespace=ToolNamespace.FS,
        description="Read multiple UTF-8 text files from the repository.",
        input_schema=ReadFilesInput,
        output_schema=FileBundle,
        permission=Permission.READ,
    )
    async def read_files(input: ReadFilesInput, context: ToolContext) -> FileBundle:
        root = Path(context.repo_root)
        files = [
            FileContent(path=rel_path(root, repo_path(root, path)), content=read_text(repo_path(root, path), input.max_bytes_per_file))
            for path in input.paths
        ]
        return FileBundle(files=files)

    @registry.tool(
        name="fs.write_file",
        namespace=ToolNamespace.FS,
        description="Write a UTF-8 text file in the repository.",
        input_schema=WriteFileInput,
        output_schema=FileContent,
        permission=Permission.WRITE,
    )
    async def write_file(input: WriteFileInput, context: ToolContext) -> FileContent:
        path = repo_path(Path(context.repo_root), input.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(input.content, encoding="utf-8")
        return FileContent(path=rel_path(Path(context.repo_root), path), content=input.content)

    @registry.tool(
        name="fs.apply_patch",
        namespace=ToolNamespace.FS,
        description="Apply a unified diff patch using git apply.",
        input_schema=ApplyPatchInput,
        output_schema=ApplyPatchOutput,
        permission=Permission.WRITE,
    )
    async def apply_patch(input: ApplyPatchInput, context: ToolContext) -> ApplyPatchOutput:
        root = Path(context.repo_root).resolve()
        changed_paths = _changed_paths_from_patch(input.patch)
        before = {
            path: (root / path).read_text(encoding="utf-8", errors="replace")
            for path in changed_paths
            if (root / path).exists()
        }
        tmp = create_temp_file(root, "patch-", ".diff", input.patch)
        git_root_output = await run_process(root, "git rev-parse --show-toplevel", context.config.command_timeout_seconds, risk=CommandRisk.LOW)
        if git_root_output.exit_code == 0:
            git_root = Path(git_root_output.stdout.strip()).resolve()
            directory = root.relative_to(git_root).as_posix()
            directory_arg = "" if directory == "." else f' --directory="{directory}"'
            command = f'git apply{directory_arg} "{tmp}"'
            output = await run_process(git_root, command, context.config.command_timeout_seconds, risk=CommandRisk.LOW)
        else:
            output = await run_process(root, f'git apply "{tmp}"', context.config.command_timeout_seconds, risk=CommandRisk.LOW)

        changed = any(
            (root / path).exists()
            and (root / path).read_text(encoding="utf-8", errors="replace") != before.get(path)
            for path in changed_paths
        )
        if changed_paths and not changed:
            changed = _apply_simple_unified_patch(root, input.patch)
        return ApplyPatchOutput(applied=changed or (output.exit_code == 0 and not changed_paths), stdout=output.stdout, stderr=output.stderr)

    @registry.tool(
        name="fs.file_exists",
        namespace=ToolNamespace.FS,
        description="Check whether a path exists inside the repository.",
        input_schema=PathInput,
        output_schema=FileExistsOutput,
        permission=Permission.READ,
    )
    async def file_exists(input: PathInput, context: ToolContext) -> FileExistsOutput:
        return FileExistsOutput(exists=repo_path(Path(context.repo_root), input.path).exists())

    @registry.tool(
        name="fs.stat_file",
        namespace=ToolNamespace.FS,
        description="Get file metadata for a repository path.",
        input_schema=PathInput,
        output_schema=StatFileOutput,
        permission=Permission.READ,
    )
    async def stat_file(input: PathInput, context: ToolContext) -> StatFileOutput:
        path = repo_path(Path(context.repo_root), input.path)
        if not path.exists():
            return StatFileOutput(exists=False)
        stat = path.stat()
        return StatFileOutput(exists=True, size=stat.st_size, modified_time=stat.st_mtime)

    @registry.tool(
        name="fs.glob",
        namespace=ToolNamespace.FS,
        description="Glob repository files by pattern.",
        input_schema=GlobInput,
        output_schema=GlobOutput,
        permission=Permission.READ,
    )
    async def glob_files(input: GlobInput, context: ToolContext) -> GlobOutput:
        root = Path(context.repo_root)
        return GlobOutput(paths=[rel_path(root, path) for path in root.glob(input.pattern)])

    @registry.tool(
        name="fs.hash_file",
        namespace=ToolNamespace.FS,
        description="Compute sha256 for a repository file.",
        input_schema=PathInput,
        output_schema=HashFileOutput,
        permission=Permission.READ,
    )
    async def hash_file(input: PathInput, context: ToolContext) -> HashFileOutput:
        return HashFileOutput(sha256=sha256_file(repo_path(Path(context.repo_root), input.path)))

    @registry.tool(
        name="fs.create_temp_file",
        namespace=ToolNamespace.FS,
        description="Create a temp file under .patchpilot/tmp.",
        input_schema=TempFileInput,
        output_schema=TempFileOutput,
        permission=Permission.WRITE,
    )
    async def temp_file(input: TempFileInput, context: ToolContext) -> TempFileOutput:
        path = create_temp_file(Path(context.repo_root), input.prefix, input.suffix, input.content)
        return TempFileOutput(path=rel_path(Path(context.repo_root), path))

    @registry.tool(
        name="fs.read_json",
        namespace=ToolNamespace.FS,
        description="Read a JSON file from the repository.",
        input_schema=PathInput,
        output_schema=JsonObject,
        permission=Permission.READ,
    )
    async def read_json(input: PathInput, context: ToolContext) -> JsonObject:
        return JsonObject(data=read_json_file(repo_path(Path(context.repo_root), input.path)))

    @registry.tool(
        name="fs.write_json",
        namespace=ToolNamespace.FS,
        description="Write a JSON file in the repository.",
        input_schema=JsonObject,
        output_schema=JsonObject,
        permission=Permission.WRITE,
    )
    async def write_json(input: JsonObject, context: ToolContext) -> JsonObject:
        path = repo_path(Path(context.repo_root), Path(".patchpilot/artifact.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(path, input.data)
        return input


def _changed_paths_from_patch(patch: str) -> list[Path]:
    paths: list[Path] = []
    for match in re.finditer(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE):
        paths.append(Path(match.group(1).strip()))
    return paths


def _apply_simple_unified_patch(root: Path, patch: str) -> bool:
    changed = False
    current: Path | None = None
    removals: list[str] = []
    additions: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = root / line.removeprefix("+++ b/").strip()
        elif line.startswith("@@"):
            removals = []
            additions = []
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            removals.append(line[1:])
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])
        elif current is not None and removals and additions:
            changed = _replace_lines(current, removals, additions) or changed
            removals = []
            additions = []
    if current is not None and removals and additions:
        changed = _replace_lines(current, removals, additions) or changed
    return changed


def _replace_lines(path: Path, removals: list[str], additions: list[str]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    old = "\n".join(removals)
    new = "\n".join(additions)
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True
