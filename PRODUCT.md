# PatchPilot Product Brief

## One-Line Concept

PatchPilot is a production-shaped repository automation agent that treats repo maintenance tasks like incidents: it investigates evidence, delegates diagnosis and review to isolated subagents, applies minimal patches, validates with tests, and returns an auditable structured report.

## Assignment Fit

Domain: repository automation.

PatchPilot is designed specifically around the five required properties from the assignment:

1. 50+ tools across 4+ namespaces.
2. Real subagent orchestration with isolated context and scoped tools.
3. Long-horizon execution over at least 20 tool calls in one session.
4. Production scaffolding: observability, retries, rate limits, typed errors, evals, and tests.
5. Composable tool inputs and outputs.

The goal is not to build a generic coding agent. The goal is to build a narrow, auditable agent harness for bounded repository maintenance loops.

## Primary User

An engineer or maintainer who wants first-pass autonomous help with small but investigation-heavy repo work:

- Fix failing tests.
- Diagnose CI-style failures.
- Perform small dependency or API migrations.
- Review a branch before opening a pull request.
- Clean up repo hygiene issues such as dead imports or outdated docs references.

## Demo Scenario

Input:

```text
Fix the failing test in this repository and explain the root cause.
```

Expected behavior:

1. Inspect repository structure.
2. Detect language and package manager.
3. Read dependency/test configuration.
4. Run the relevant test command.
5. Parse the failure.
6. Search for related symbols/files.
7. Spawn a diagnosis subagent with read/search/test-output tools only.
8. Build a patch plan from structured evidence.
9. Apply a minimal patch.
10. Run targeted tests.
11. Iterate if the first patch fails.
12. Run the broader test suite.
13. Capture git diff.
14. Spawn a review subagent with diff/test/log tools only.
15. Apply review feedback if needed.
16. Produce a final structured report.

The demo should visibly cross 20+ tool calls in one session.

## Model Provider

PatchPilot will use OpenRouter as the model gateway.

Rationale:

- Allows model choice without changing the agent runtime.
- Makes it easy to compare coding-focused, reasoning-focused, and low-cost models.
- Keeps provider logic isolated behind one model client interface.

Runtime configuration:

```text
OPENROUTER_API_KEY=...
PATCHPILOT_MODEL=anthropic/claude-sonnet-4.5
PATCHPILOT_BASE_URL=https://openrouter.ai/api/v1
```

The code should not hard-code one model. It should expose:

- `OpenRouterModelClient` for live runs.
- `FakeModelClient` for unit tests, integration tests, and deterministic evals.
- Optional model aliases in config, such as `fast`, `strong`, and `cheap`.

## Recommended Stack

- Python: main implementation language.
- LangGraph: stateful execution substrate for the parent agent flow.
- Pydantic: typed tool inputs, outputs, state, and subagent results.
- Typer: CLI entrypoint.
- Tenacity: retries with exponential backoff.
- aiolimiter: model and external-call rate limits.
- structlog: structured logs and trace events.
- pytest: unit, integration, and eval tests.

## Core Architecture

```text
Typer CLI
  -> loads config
  -> creates session state
  -> starts LangGraph runtime

LangGraph parent agent
  -> plans
  -> selects tools from registry
  -> executes tools through ToolExecutor
  -> spawns scoped subagents
  -> compacts context
  -> finalizes structured report

ToolRegistry
  -> stores 50+ typed tools
  -> groups tools by namespace
  -> validates input/output schemas
  -> applies permissions, retries, rate limits, and logging

SubagentRuntime
  -> receives isolated task context
  -> receives scoped tool set
  -> returns structured result to parent

TraceStore
  -> writes JSONL trace events
  -> records model calls, tool calls, errors, duration, and artifacts
```

## Tool Namespaces

PatchPilot should have at least 50 tools across these namespaces.

### fs

- `fs.list_dir`
- `fs.read_file`
- `fs.read_files`
- `fs.write_file`
- `fs.apply_patch`
- `fs.file_exists`
- `fs.stat_file`
- `fs.glob`
- `fs.hash_file`
- `fs.create_temp_file`
- `fs.read_json`
- `fs.write_json`

### git

- `git.status`
- `git.diff`
- `git.diff_file`
- `git.log`
- `git.show`
- `git.blame`
- `git.branch`
- `git.changed_files`
- `git.staged_files`
- `git.root`
- `git.merge_base`
- `git.clean_check`
- `git.summarize_diff`

### code

- `code.detect_language`
- `code.detect_package_manager`
- `code.find_tests`
- `code.find_symbols`
- `code.search_text`
- `code.search_regex`
- `code.parse_imports`
- `code.build_file_bundle`
- `code.rank_relevant_files`
- `code.extract_failure_locations`
- `code.map_test_to_source`
- `code.validate_patch_shape`
- `code.summarize_files`

### exec

- `exec.run_command`
- `exec.run_tests`
- `exec.run_targeted_test`
- `exec.run_linter`
- `exec.run_typecheck`
- `exec.run_formatter`
- `exec.capture_env`
- `exec.check_command_exists`
- `exec.detect_test_command`
- `exec.command_history`
- `exec.kill_process`
- `exec.timeout_probe`

### memory_eval

- `memory.add_observation`
- `memory.summarize_context`
- `memory.retrieve_artifacts`
- `memory.record_decision`
- `eval.load_fixture`
- `eval.score_run`
- `eval.compare_expected_files`
- `eval.assert_trace_property`
- `eval.export_session`

This gives 57 named tools before any optional expansion.

## Subagents

### DiagnosisAgent

Purpose: identify root cause from evidence.

Scoped tools:

- read-only filesystem tools
- code search tools
- git diff/log tools
- test-output inspection tools

Structured output:

```json
{
  "root_cause": "string",
  "evidence": [
    {
      "file_path": "string",
      "line": 0,
      "reason": "string"
    }
  ],
  "recommended_fix": "string",
  "confidence": 0.0
}
```

### ReviewAgent

Purpose: review the produced diff before finalization.

Scoped tools:

- git diff tools
- test result tools
- read-only file tools

Structured output:

```json
{
  "approved": true,
  "issues": [
    {
      "severity": "low|medium|high",
      "file_path": "string",
      "message": "string"
    }
  ],
  "recommended_changes": ["string"]
}
```

### TestPlannerAgent

Purpose: choose the smallest useful test sequence.

Scoped tools:

- package/test detection tools
- read-only repository inspection tools

Structured output:

```json
{
  "targeted_commands": ["string"],
  "full_commands": ["string"],
  "reasoning": "string"
}
```

## Composable Tool Chains

PatchPilot should show structured output composition explicitly:

```text
code.search_text -> SearchResult[]
fs.read_files -> FileBundle, consumes SearchResult[].file_path
DiagnosisAgent.run -> DiagnosisResult, consumes FileBundle + TestResult
code.validate_patch_shape -> PatchValidation, consumes PatchPlan
fs.apply_patch -> PatchApplyResult, consumes PatchPlan
exec.run_targeted_test -> TestResult, consumes changed files
git.diff -> DiffResult, consumes patched repo state
ReviewAgent.run -> ReviewResult, consumes DiffResult + TestResult
FinalReport -> consumes DiagnosisResult + PatchApplyResult + ReviewResult
```

## Context Strategy

The session state should be explicit in code:

```text
goal
plan
current_step
observations
tool_call_history
artifacts
subagent_results
memory_summary
budgets
final_report
```

Compaction rule:

- Keep recent tool calls verbatim.
- Summarize older observations into `memory_summary`.
- Preserve structured artifacts, diffs, errors, and subagent outputs.
- Never summarize away the current plan, open risks, or test results.

## Production Scaffolding

Required implementation pieces:

- Structured JSONL traces with `trace_id`, `session_id`, `tool_name`, `duration_ms`, and `error_type`.
- Retry policies with exponential backoff for model calls and retryable tools.
- Rate limits for model calls and external calls.
- Typed errors:
  - `PatchPilotError`
  - `ToolError`
  - `ToolValidationError`
  - `ModelError`
  - `RateLimitError`
  - `SubagentError`
  - `ExecutionTimeoutError`
- Unit tests for registry, schemas, retry logic, rate limits, and context compaction.
- Integration test for a full fixture-repo repair run.
- Eval harness that checks trace properties, final report structure, changed files, and test outcomes.

## Open-Source References

These projects are references for architecture patterns, not codebases to fork wholesale.

- LangGraph: stateful agent/workflow execution substrate.
  - https://github.com/langchain-ai/langgraph
- Deep Agents: subagent patterns, planning, filesystem-style state, and long-horizon task flow.
  - https://github.com/langchain-ai/deepagents
- langgraph-bigtool: scalable tool registry and large tool-selection patterns.
  - https://github.com/langchain-ai/langgraph-bigtool
- OpenHands: software agent runtime, sandboxing ideas, event stream architecture, and coding-agent ergonomics.
  - https://github.com/OpenHands/OpenHands
- OpenHands Software Agent SDK: lower-level software-agent interfaces and execution patterns.
  - https://github.com/OpenHands/software-agent-sdk
- SWE-agent: repository automation flow, command execution, and software engineering task loops.
  - https://github.com/SWE-agent/SWE-agent
- Aider: repo map, patch workflows, and practical coding-assistant UX patterns.
  - https://github.com/Aider-AI/aider
- IncidentFox: incident-style investigation framing for engineering operations.
  - https://github.com/incidentfox/incidentfox
- K8sGPT: diagnostic-agent style for infrastructure investigation.
  - https://github.com/k8sgpt-ai/k8sgpt
- HolmesGPT: observability-driven investigation and remediation patterns.
  - https://github.com/HolmesGPT/holmesgpt

PatchPilot should cite these in the project documentation as inspiration only. The submitted repository should contain original implementation for the assignment-critical parts: tool registry, tool schemas, subagent contracts, context strategy, eval harness, and traces.

## Deliverables

- Public GitHub repository.
- Commit history showing incremental build.
- `MEMO.md` at repository root.
- Three-to-five-minute video walkthrough.
- Native Codex session export.
- Working CLI demo.
- Test and eval output included in repository artifacts or docs.

## Five-Day Build Plan

### Day 1

- Scaffold Python project.
- Add Typer CLI.
- Add config for OpenRouter.
- Implement model client interface plus fake model client.
- Implement typed tool registry skeleton.
- Add first batch of filesystem/git tools.

### Day 2

- Complete 50+ tool definitions across namespaces.
- Add Pydantic schemas.
- Add ToolExecutor with retries, rate limits, and structured logs.
- Add unit tests for registry and tool validation.

### Day 3

- Implement LangGraph parent flow.
- Add explicit session state and context compaction.
- Implement DiagnosisAgent and ReviewAgent with scoped tools.
- Add structured subagent result contracts.

### Day 4

- Build fixture repos.
- Implement full repair loop.
- Add eval harness and integration test.
- Record a 20+ tool-call trace.

### Day 5

- Polish CLI and docs.
- Write `MEMO.md`.
- Run tests/evals.
- Record video walkthrough.
- Export Codex traces.
- Push public GitHub repository.

## Defensible Design Decision

PatchPilot uses LangGraph as the execution substrate but keeps the assignment-critical architecture custom.

Defensible argument:

Using LangGraph avoids spending the five-day window rebuilding generic graph execution, while the project still owns the tool registry, typed contracts, subagent isolation, context compaction, eval harness, and production scaffolding. The alternative of using a full coding-agent framework like OpenHands or SWE-agent would provide too much of the domain behavior out of the box and make the submitted work less clearly original.
