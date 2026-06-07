"""Code inspection tools."""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from patchpilot.schemas.common import FileBundle, FileContent, PathInput, Permission, SearchResult, SearchResults, TextOutput, ToolNamespace
from patchpilot.schemas.tool_io import (
    DetectLanguageOutput,
    DetectPackageManagerOutput,
    FailureLocationsInput,
    FailureLocationsOutput,
    FindTestsOutput,
    ParseImportsInput,
    ParseImportsOutput,
    PatchEdit,
    PatchValidationInput,
    PatchValidationOutput,
    SearchRegexInput,
    SearchTextInput,
    SummarizeFilesInput,
)
from patchpilot.adapters.python_pytest import PythonPytestAdapter
from patchpilot.tools.helpers import grep_regex, grep_text, iter_repo_files, read_text, rel_path, repo_path
from patchpilot.tools.registry import ToolContext, ToolRegistry


LANG_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}


def register(registry: ToolRegistry) -> None:
    @registry.tool(
        name="code.detect_language",
        namespace=ToolNamespace.CODE,
        description="Detect languages from file extensions.",
        input_schema=PathInput,
        output_schema=DetectLanguageOutput,
        permission=Permission.READ,
    )
    async def detect_language(input: PathInput, context: ToolContext) -> DetectLanguageOutput:
        root = repo_path(Path(context.repo_root), input.path)
        counts = Counter()
        for path in iter_repo_files(root):
            language = LANG_EXTENSIONS.get(path.suffix)
            if language:
                counts[language] += 1
        primary = counts.most_common(1)[0][0] if counts else None
        return DetectLanguageOutput(languages=dict(counts), primary_language=primary)

    @registry.tool(
        name="code.detect_package_manager",
        namespace=ToolNamespace.CODE,
        description="Detect likely package managers from repository files.",
        input_schema=PathInput,
        output_schema=DetectPackageManagerOutput,
        permission=Permission.READ,
    )
    async def detect_package_manager(input: PathInput, context: ToolContext) -> DetectPackageManagerOutput:
        root = repo_path(Path(context.repo_root), input.path)
        markers = {
            "uv": "uv.lock",
            "poetry": "poetry.lock",
            "pip": "requirements.txt",
            "python-build": "pyproject.toml",
            "npm": "package-lock.json",
            "pnpm": "pnpm-lock.yaml",
            "go": "go.mod",
        }
        managers = [name for name, marker in markers.items() if (root / marker).exists()]
        return DetectPackageManagerOutput(managers=managers)

    @registry.tool(
        name="code.find_tests",
        namespace=ToolNamespace.CODE,
        description="Find likely test files.",
        input_schema=PathInput,
        output_schema=FindTestsOutput,
        permission=Permission.READ,
    )
    async def find_tests(input: PathInput, context: ToolContext) -> FindTestsOutput:
        root = repo_path(Path(context.repo_root), input.path)
        files = [
            rel_path(Path(context.repo_root), path)
            for path in iter_repo_files(root)
            if path.is_file()
            and (path.name.startswith("test_") or path.name.endswith("_test.py") or path.name.endswith(".test.ts") or path.name.endswith("_test.go"))
        ]
        return FindTestsOutput(test_files=files)

    @registry.tool(
        name="code.find_symbols",
        namespace=ToolNamespace.CODE,
        description="Find Python function/class symbols by name.",
        input_schema=SearchTextInput,
        output_schema=SearchResults,
        permission=Permission.READ,
    )
    async def find_symbols(input: SearchTextInput, context: ToolContext) -> SearchResults:
        pattern = re.compile(rf"^\s*(def|class)\s+{re.escape(input.query)}\b")
        rows = grep_regex(repo_path(Path(context.repo_root), input.path), pattern.pattern, input.max_results)
        return SearchResults(results=[SearchResult(file_path=rel_path(Path(context.repo_root), p), line=line, snippet=s) for p, line, s in rows])

    @registry.tool(
        name="code.search_text",
        namespace=ToolNamespace.CODE,
        description="Search repository text for a literal query.",
        input_schema=SearchTextInput,
        output_schema=SearchResults,
        permission=Permission.READ,
    )
    async def search_text(input: SearchTextInput, context: ToolContext) -> SearchResults:
        rows = grep_text(repo_path(Path(context.repo_root), input.path), input.query, input.max_results)
        return SearchResults(results=[SearchResult(file_path=rel_path(Path(context.repo_root), p), line=line, snippet=s) for p, line, s in rows])

    @registry.tool(
        name="code.search_regex",
        namespace=ToolNamespace.CODE,
        description="Search repository text with a regular expression.",
        input_schema=SearchRegexInput,
        output_schema=SearchResults,
        permission=Permission.READ,
    )
    async def search_regex(input: SearchRegexInput, context: ToolContext) -> SearchResults:
        rows = grep_regex(repo_path(Path(context.repo_root), input.path), input.pattern, input.max_results)
        return SearchResults(results=[SearchResult(file_path=rel_path(Path(context.repo_root), p), line=line, snippet=s) for p, line, s in rows])

    @registry.tool(
        name="code.parse_imports",
        namespace=ToolNamespace.CODE,
        description="Parse imports from a Python file.",
        input_schema=ParseImportsInput,
        output_schema=ParseImportsOutput,
        permission=Permission.READ,
    )
    async def parse_imports(input: ParseImportsInput, context: ToolContext) -> ParseImportsOutput:
        path = repo_path(Path(context.repo_root), input.path)
        tree = ast.parse(read_text(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return ParseImportsOutput(imports=imports)

    @registry.tool(
        name="code.build_file_bundle",
        namespace=ToolNamespace.CODE,
        description="Build a structured bundle of relevant files.",
        input_schema=SummarizeFilesInput,
        output_schema=FileBundle,
        permission=Permission.READ,
    )
    async def build_file_bundle(input: SummarizeFilesInput, context: ToolContext) -> FileBundle:
        root = Path(context.repo_root)
        return FileBundle(files=[FileContent(path=path, content=read_text(repo_path(root, path), input.max_chars_per_file)) for path in input.paths])

    @registry.tool(
        name="code.rank_relevant_files",
        namespace=ToolNamespace.CODE,
        description="Rank files by literal query frequency.",
        input_schema=SearchTextInput,
        output_schema=SearchResults,
        permission=Permission.READ,
    )
    async def rank_relevant_files(input: SearchTextInput, context: ToolContext) -> SearchResults:
        return await search_text(input, context)

    @registry.tool(
        name="code.extract_failure_locations",
        namespace=ToolNamespace.CODE,
        description="Extract file:line patterns from test output.",
        input_schema=FailureLocationsInput,
        output_schema=FailureLocationsOutput,
        permission=Permission.READ,
    )
    async def extract_failure_locations(input: FailureLocationsInput, context: ToolContext) -> FailureLocationsOutput:
        matches = re.findall(r"([A-Za-z0-9_./\\-]+\.py:\d+)", input.output)
        return FailureLocationsOutput(locations=matches)

    @registry.tool(
        name="code.map_test_to_source",
        namespace=ToolNamespace.CODE,
        description="Map a test path to likely source path candidates.",
        input_schema=PathInput,
        output_schema=SearchResults,
        permission=Permission.READ,
    )
    async def map_test_to_source(input: PathInput, context: ToolContext) -> SearchResults:
        root = Path(context.repo_root)
        candidates = PythonPytestAdapter().source_candidates_for_test(root, Path(input.path))
        results: list[SearchResult] = [
            SearchResult(file_path=path, line=1, snippet="import-linked source candidate")
            for path in candidates
        ]
        seen = {result.file_path.as_posix() for result in results}
        stem = Path(input.path).stem.replace("test_", "")
        for path, line, snippet in grep_text(root, stem, 20):
            rel = rel_path(root, path)
            if rel.as_posix() in seen or _is_test_path(rel) or rel.suffix != ".py":
                continue
            seen.add(rel.as_posix())
            results.append(SearchResult(file_path=rel, line=line, snippet=snippet))
        return SearchResults(results=results[:20])

    @registry.tool(
        name="code.validate_patch_shape",
        namespace=ToolNamespace.CODE,
        description="Validate a patch plan shape against protected path and diff constraints.",
        input_schema=PatchValidationInput,
        output_schema=PatchValidationOutput,
        permission=Permission.READ,
    )
    async def validate_patch_shape(input: PatchValidationInput, context: ToolContext) -> PatchValidationOutput:
        reasons: list[str] = []
        semantic_reasons: list[str] = []
        root = Path(context.repo_root)
        patch_plan = input.patch_plan or {}
        patch_text = input.patch or str(patch_plan.get("patch") or patch_plan.get("unified_diff") or "")
        structured_edits = input.structured_edits
        if not structured_edits and patch_plan.get("edits"):
            structured_edits = [PatchEdit.model_validate(edit) for edit in patch_plan.get("edits", [])]
        evidence_refs = input.evidence_refs or list(patch_plan.get("evidence_refs") or [])
        root_cause = input.root_cause or str(patch_plan.get("root_cause") or "")
        normalized_targets: list[Path] = []
        for target in input.target_files:
            try:
                rel = rel_path(root, repo_path(root, target))
                normalized_targets.append(rel)
            except Exception as exc:
                reasons.append(f"path escapes repo: {target}")
                continue
            for protected in input.protected_paths:
                protected_text = protected.as_posix().rstrip("/")
                if rel.as_posix() == protected_text or rel.as_posix().startswith(f"{protected_text}/"):
                    reasons.append(f"protected path: {rel}")
        patch_lines = 0
        patch_targets: list[Path] = []
        normalized_patch_targets: list[Path] = []
        if patch_text:
            patch_lines = len([line for line in patch_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))])
            if patch_lines > input.max_diff_lines:
                reasons.append(f"diff too large: {patch_lines} lines exceeds {input.max_diff_lines}")
            patch_targets = _changed_paths_from_patch_text(patch_text)
            for target in patch_targets:
                try:
                    rel = rel_path(root, repo_path(root, target))
                    normalized_patch_targets.append(rel)
                    for protected in input.protected_paths:
                        protected_text = protected.as_posix().rstrip("/")
                        if rel.as_posix() == protected_text or rel.as_posix().startswith(f"{protected_text}/"):
                            reasons.append(f"protected path: {rel}")
                    if rel not in normalized_targets:
                        reasons.append(f"patch touches undeclared file: {rel}")
                    if _is_binary_path(root, rel):
                        reasons.append(f"binary file edit rejected: {rel}")
                except Exception:
                    reasons.append(f"path escapes repo: {target}")
        if normalized_targets and not input.allow_test_only:
            test_targets = [path for path in normalized_targets if _is_test_path(path)]
            if test_targets:
                reasons.append(f"test edits rejected: {', '.join(path.as_posix() for path in test_targets)}")
        edit_paths = _normalize_edit_paths(root, structured_edits, reasons)
        _validate_structured_edits(root, structured_edits, edit_paths, input, reasons, semantic_reasons)
        if structured_edits and normalized_patch_targets:
            if set(edit_paths) != set(normalized_patch_targets):
                reasons.append(
                    "structured edits and unified diff touch different files: "
                    f"structured={sorted(path.as_posix() for path in edit_paths)} "
                    f"diff={sorted(path.as_posix() for path in normalized_patch_targets)}"
            )
            for edit in structured_edits:
                try:
                    rel = rel_path(root, repo_path(root, edit.path))
                except Exception:
                    continue
                if rel in normalized_patch_targets and not _diff_contains_edit(patch_text, edit):
                    reasons.append(f"structured edit does not match unified diff intent: {rel}")
        changed_files = normalized_patch_targets or edit_paths or normalized_targets
        if normalized_targets:
            for edit_path in edit_paths:
                if edit_path not in normalized_targets:
                    reasons.append(f"structured edit touches undeclared file: {edit_path}")
        changed_set = set(changed_files)
        if normalized_targets:
            missing_concrete_edits = sorted(path.as_posix() for path in set(normalized_targets) - changed_set)
            if missing_concrete_edits:
                reasons.append(f"target file lacks concrete edit: {', '.join(missing_concrete_edits)}")
        if changed_files and not evidence_refs:
            semantic_reasons.append("changed files require evidence_refs")
        if len(changed_files) > 1 and not root_cause.strip():
            semantic_reasons.append("multi-file patch requires shared root_cause")
        for edit in structured_edits:
            try:
                rel = rel_path(root, repo_path(root, edit.path))
            except Exception:
                continue
            edit_evidence = edit.evidence_refs or evidence_refs
            if not edit_evidence:
                semantic_reasons.append(f"missing evidence link for changed file: {rel}")
            if len(changed_files) > 1 and not (edit.root_cause_linkage or root_cause).strip():
                semantic_reasons.append(f"missing same-root-cause linkage for changed file: {rel}")
        if normalized_targets and not input.allow_test_only and all(_is_test_path(path) for path in normalized_targets):
            reasons.append("test-only patch rejected")
        reasons.extend(semantic_reasons)
        output = PatchValidationOutput(
            valid=len(reasons) == 0,
            reasons=reasons,
            target_files=normalized_targets,
            changed_files=changed_files,
            diff_lines=patch_lines,
            semantic_reasons=semantic_reasons,
        )
        context.artifacts["patch_validation"] = output.model_dump(mode="json")
        if not output.valid:
            context.artifacts.setdefault("rejected_patch_plans", []).append(
                {
                    "patch_plan": patch_plan,
                    "validation": output.model_dump(mode="json"),
                }
            )
        return output

    @registry.tool(
        name="code.summarize_files",
        namespace=ToolNamespace.CODE,
        description="Create compact summaries of selected files.",
        input_schema=SummarizeFilesInput,
        output_schema=TextOutput,
        permission=Permission.READ,
    )
    async def summarize_files(input: SummarizeFilesInput, context: ToolContext) -> TextOutput:
        chunks = []
        root = Path(context.repo_root)
        for path in input.paths:
            full = repo_path(root, path)
            content = read_text(full, input.max_chars_per_file)
            chunks.append(f"## {path}\n{content[:input.max_chars_per_file]}")
        return TextOutput(text="\n\n".join(chunks))


def _changed_paths_from_patch_text(patch: str) -> list[Path]:
    return [Path(match.group(1).strip()) for match in re.finditer(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)]


def _is_test_path(path: Path) -> bool:
    text = path.as_posix()
    return "/tests/" in f"/{text}" or path.name.startswith("test_") or path.name.endswith("_test.py")


def _normalize_edit_paths(root: Path, edits: list, reasons: list[str]) -> list[Path]:
    paths: list[Path] = []
    for edit in edits:
        try:
            paths.append(rel_path(root, repo_path(root, edit.path)))
        except Exception:
            reasons.append(f"path escapes repo: {edit.path}")
    return paths


def _validate_structured_edits(
    root: Path,
    edits: list[PatchEdit],
    edit_paths: list[Path],
    input: PatchValidationInput,
    reasons: list[str],
    semantic_reasons: list[str],
) -> None:
    for edit, rel in zip(edits, edit_paths):
        protected_hit = _protected_path_reason(rel, input.protected_paths)
        if protected_hit:
            reasons.append(protected_hit)
        if _is_binary_path(root, rel):
            reasons.append(f"binary file edit rejected: {rel}")
        if not input.allow_test_only and _is_test_path(rel):
            reasons.append(f"test edits rejected: {rel}")
        if not edit.before:
            reasons.append(f"structured edit missing SEARCH text: {rel}")
            continue
        target = repo_path(root, rel)
        if not target.exists():
            reasons.append(f"structured edit target missing: {rel}")
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        count = _search_count(text, edit.before)
        if count == 0:
            reasons.append(f"structured edit SEARCH text not found: {rel}")
        elif count > 1:
            reasons.append(f"ambiguous structured edit SEARCH text occurs {count} times: {rel}")
        if edit.before == edit.after:
            reasons.append(f"structured edit is a no-op: {rel}")
        if not (edit.evidence_refs or input.evidence_refs):
            semantic_reasons.append(f"missing evidence link for changed file: {rel}")
        if not (edit.root_cause_linkage or input.root_cause).strip():
            semantic_reasons.append(f"missing same-root-cause linkage for changed file: {rel}")


def _protected_path_reason(path: Path, protected_paths: list[Path]) -> str | None:
    for protected in protected_paths:
        protected_text = protected.as_posix().rstrip("/")
        if path.as_posix() == protected_text or path.as_posix().startswith(f"{protected_text}/"):
            return f"protected path: {path}"
    return None


def _search_count(text: str, search: str) -> int:
    count = text.count(search)
    if count:
        return count
    return text.replace("\r\n", "\n").count(search.replace("\r\n", "\n"))


def _diff_contains_edit(patch: str, edit) -> bool:
    removed = [line for line in edit.before.splitlines() if line.strip()]
    added = [line for line in edit.after.splitlines() if line.strip()]
    diff_removed = [line[1:].strip() for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
    diff_added = [line[1:].strip() for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
    removed_ok = not removed or any(line.strip() in diff_removed for line in removed)
    added_ok = not added or any(line.strip() in diff_added for line in added)
    return removed_ok and added_ok


def _is_binary_path(root: Path, path: Path) -> bool:
    target = repo_path(root, path)
    if not target.exists() or not target.is_file():
        return False
    data = target.read_bytes()[:1024]
    return b"\0" in data
