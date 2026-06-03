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
    PatchValidationInput,
    PatchValidationOutput,
    SearchRegexInput,
    SearchTextInput,
    SummarizeFilesInput,
)
from patchpilot.tools.helpers import grep_regex, grep_text, read_text, rel_path, repo_path
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
        for path in root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
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
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
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
        stem = Path(input.path).stem.replace("test_", "")
        rows = grep_text(Path(context.repo_root), stem, 20)
        return SearchResults(results=[SearchResult(file_path=rel_path(Path(context.repo_root), p), line=line, snippet=s) for p, line, s in rows])

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
        for target in input.target_files:
            for protected in input.protected_paths:
                if str(target).startswith(str(protected)):
                    reasons.append(f"protected path: {target}")
        return PatchValidationOutput(valid=len(reasons) == 0, reasons=reasons)

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

