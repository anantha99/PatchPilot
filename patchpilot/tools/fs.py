"""Repository-bound filesystem tools for safe reads and validated patch writes."""

from __future__ import annotations

import re
import difflib
from pathlib import Path

from patchpilot.schemas.common import (
    CommandRisk,
    FileBundle,
    FileContent,
    FileReadError,
    JsonObject,
    PathInput,
    Permission,
    ToolNamespace,
)
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
    WriteJsonInput,
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
        files: list[FileContent] = []
        missing_files: list[Path] = []
        errors: list[FileReadError] = []
        for requested_path in input.paths:
            try:
                path = repo_path(root, requested_path)
                content = read_text(path, input.max_bytes_per_file)
            except FileNotFoundError as exc:
                missing_files.append(requested_path)
                errors.append(
                    FileReadError(
                        path=requested_path,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                )
                continue
            except OSError as exc:
                errors.append(
                    FileReadError(
                        path=requested_path,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                )
                continue
            except Exception as exc:
                errors.append(
                    FileReadError(
                        path=requested_path,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                )
                continue
            files.append(FileContent(path=rel_path(root, path), content=content))
        return FileBundle(files=files, missing_files=missing_files, errors=errors)

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
        changed_paths = list(dict.fromkeys([*_changed_paths_from_patch(input.patch), *_changed_paths_from_structured_edits(input.structured_edits)]))
        _validate_patch_paths(root, changed_paths)
        before = _path_hashes(root, changed_paths)
        before_text = _path_texts(root, changed_paths)
        apply_stdout = ""
        apply_stderr = ""
        git_apply_exit_code = 1
        if changed_paths and input.structured_edits:
            _apply_structured_edits(root, input.structured_edits)
        after = _path_hashes(root, changed_paths)
        actual_changed = _changed_path_subset(before, after)
        if not actual_changed and input.patch.strip():
            tmp = create_temp_file(root, "patch-", ".diff", input.patch)
            git_root_output = await run_process(root, "git rev-parse --show-toplevel", context.config.command_timeout_seconds, risk=CommandRisk.LOW)
            is_git_worktree = git_root_output.exit_code == 0
            if is_git_worktree:
                git_root = Path(git_root_output.stdout.strip()).resolve()
                directory = root.relative_to(git_root).as_posix()
                directory_arg = "" if directory == "." else f' --directory="{directory}"'
                command = f'git apply{directory_arg} "{tmp}"'
                output = await run_process(git_root, command, context.config.command_timeout_seconds, risk=CommandRisk.LOW)
            else:
                output = await run_process(root, f'git apply "{tmp}"', context.config.command_timeout_seconds, risk=CommandRisk.LOW)
            apply_stdout = output.stdout
            apply_stderr = output.stderr
            git_apply_exit_code = output.exit_code
            after = _path_hashes(root, changed_paths)
            actual_changed = _changed_path_subset(before, after)
            if not actual_changed and output.exit_code != 0:
                _apply_simple_unified_patch(root, input.patch)
                after = _path_hashes(root, changed_paths)
                actual_changed = _changed_path_subset(before, after)
        after_text = _path_texts(root, changed_paths)
        clean_diff = _clean_diff(before_text, after_text)
        satisfied = _structured_edits_satisfied(root, input.structured_edits)
        applied = bool(actual_changed) or (not changed_paths and git_apply_exit_code == 0) or satisfied
        if applied:
            context.artifacts.setdefault("applied_patches", []).append(
                {
                    "patch": clean_diff or input.patch,
                    "original_patch": input.patch,
                    "clean_diff": clean_diff,
                    "changed_files": [path.as_posix() for path in (actual_changed or changed_paths)],
                    "hunks_applied": input.patch.count("\n@@"),
                }
            )
        return ApplyPatchOutput(
            applied=applied,
            stdout=apply_stdout,
            stderr=apply_stderr,
            changed_files=(actual_changed or changed_paths) if applied else [],
            hunks_applied=input.patch.count("\n@@"),
            clean_diff=clean_diff,
            summary=f"Applied structured edits to {len(actual_changed or changed_paths)} file(s)" if applied and input.structured_edits else (f"Applied patch to {len(actual_changed)} file(s)" if applied else "Patch produced no changes"),
        )

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
        input_schema=WriteJsonInput,
        output_schema=JsonObject,
        permission=Permission.WRITE,
    )
    async def write_json(input: WriteJsonInput, context: ToolContext) -> JsonObject:
        path = repo_path(Path(context.repo_root), input.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(path, input.data)
        return JsonObject(data={"path": rel_path(Path(context.repo_root), path), "data": input.data})


def _changed_paths_from_patch(patch: str) -> list[Path]:
    paths: list[Path] = []
    for match in re.finditer(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE):
        paths.append(Path(match.group(1).strip()))
    return paths


def _changed_paths_from_structured_edits(edits: list[dict]) -> list[Path]:
    paths: list[Path] = []
    for edit in edits:
        path = edit.get("path") or edit.get("file")
        if path:
            paths.append(Path(str(path).strip()))
    return paths


def _validate_patch_paths(root: Path, paths: list[Path]) -> None:
    for path in paths:
        repo_path(root, path)


def _path_hashes(root: Path, paths: list[Path]) -> dict[Path, str | None]:
    return {
        path: sha256_file(resolved) if (resolved := repo_path(root, path)).exists() else None
        for path in paths
    }


def _path_texts(root: Path, paths: list[Path]) -> dict[Path, str]:
    texts: dict[Path, str] = {}
    for path in paths:
        resolved = repo_path(root, path)
        if resolved.exists():
            texts[path] = resolved.read_text(encoding="utf-8", errors="replace")
        else:
            texts[path] = ""
    return texts


def _changed_path_subset(before: dict[Path, str | None], after: dict[Path, str | None]) -> list[Path]:
    return [path for path in after if before.get(path) != after.get(path)]


def _apply_simple_unified_patch(root: Path, patch: str) -> bool:
    changed = False
    current: Path | None = None
    removals: list[str] = []
    additions: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current = repo_path(root, line.removeprefix("+++ b/").strip())
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


def _apply_structured_edits(root: Path, edits: list[dict]) -> bool:
    changed = False
    for edit in edits:
        path_value = edit.get("path") or edit.get("file")
        before = edit.get("before") if edit.get("before") is not None else edit.get("old_text")
        after = edit.get("after") if edit.get("after") is not None else edit.get("new_text")
        if not path_value or before is None or after is None:
            continue
        changed = _replace_text(repo_path(root, Path(str(path_value))), str(before), str(after)) or changed
    return changed


def _structured_edits_satisfied(root: Path, edits: list[dict]) -> bool:
    if not edits:
        return False
    for edit in edits:
        path_value = edit.get("path") or edit.get("file")
        after = edit.get("after") if edit.get("after") is not None else edit.get("new_text")
        if not path_value or after is None:
            return False
        path = repo_path(root, Path(str(path_value)))
        if not path.exists():
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
        if str(after) not in text and str(after).replace("\r\n", "\n") not in text.replace("\r\n", "\n"):
            return False
    return True


def _replace_text(path: Path, old: str, new: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if old not in text:
        old_lf = old.replace("\r\n", "\n")
        text_lf = text.replace("\r\n", "\n")
        count = text_lf.count(old_lf)
        if count != 1:
            return False
        new_lf = new.replace("\r\n", "\n")
        path.write_text(text_lf.replace(old_lf, new_lf, 1), encoding="utf-8")
        return True
    if text.count(old) != 1:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def _clean_diff(before: dict[Path, str], after: dict[Path, str]) -> str:
    chunks: list[str] = []
    for path in after:
        old = before.get(path, "")
        new = after.get(path, "")
        if old == new:
            continue
        chunks.extend(
            difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=f"a/{path.as_posix()}",
                tofile=f"b/{path.as_posix()}",
                lineterm="",
            )
        )
    return "\n".join(chunks) + ("\n" if chunks else "")


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
