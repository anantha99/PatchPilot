# PatchPilot PRD

## 1. Summary

PatchPilot is a Product v1 for autonomous failing-test repair in local repositories. It treats a bounded repository failure like an incident: inspect the repo, reproduce the failure, gather evidence, delegate diagnosis and review to scoped subagents, plan a minimal patch, validate with tests, and emit an auditable structured report.

The first release is deliberately shaped around the X-ARC five-day engineering assignment. Passing the assignment is the v1 release gate, not a side demo: every product requirement below should help prove typed tool use, subagent isolation, long-horizon execution, production scaffolding, and composable tool I/O.

Primary product claim:

```text
Given a local repository and a failing test command, PatchPilot can autonomously attempt a bounded repair loop and explain the root cause, patch, validation results, review outcome, and residual risks.
```

Primary release claim:

```text
PatchPilot v1 passes the X-ARC requirements through a reliable Python/pytest failing-test repair demo, while preserving a product-shaped architecture for later maintenance tasks.
```

## 2. Product Positioning

PatchPilot is not a general-purpose coding agent. It is a repository maintenance harness for bounded repair loops where the success condition is observable through tests and trace evidence.

The Product v1 wedge is **failing-test repair**:

- It has a clear trigger: a known or discoverable failing test command.
- It has a measurable end state: targeted and broader validation pass, fail, or exhaust budget.
- It exercises the full agent architecture: tool selection, state, subagents, patch planning, validation, review, and reporting.
- It supports the assignment better than a broader repo-maintenance queue because the evaluation can inspect concrete trace properties and test outcomes.

Future product directions such as dependency migrations, branch review, docs hygiene, and CI integration are deferred until the failing-test loop is credible.

## 3. Problem Frame

Engineering teams repeatedly spend time on first-pass repository repair work:

- Reproducing failing tests.
- Mapping failure output to likely source and test files.
- Reading nearby implementation and tests.
- Making a small evidence-backed patch.
- Re-running targeted and broad validation.
- Reviewing diffs before opening a pull request.
- Writing a root-cause summary that another engineer can trust.

Most coding assistants can help interactively, but PatchPilot must demonstrate an autonomous production-shaped harness. The product needs typed tools, explicit state, controlled command execution, traceability, isolated subagents, retry and budget behavior, deterministic evals, and reports that can be audited after the run.

For the X-ARC assignment, architectural credibility matters as much as raw repair capability. A narrow failing-test product with a complete repair loop is stronger than a broad coding assistant with shallow scaffolding.

## 4. Target Users

Primary v1 user:

- An engineer, maintainer, or technical reviewer who wants autonomous first-pass help on a bounded failing-test repair.

Assignment reviewer:

- A reviewer evaluating whether the codebase visibly satisfies the five X-ARC properties through implementation, tests, traces, and `MEMO.md`.

Future secondary users:

- Maintainers triaging repo hygiene tasks.
- Reviewers checking an existing branch before PR creation.
- Teams collecting repeatable repair traces for evaluation.

## 5. Goals

### Product Goals

- Complete one full failing-test repair loop on a fixture repository.
- Attempt the same loop on a real local repository when a test command is supplied or discoverable.
- Preserve enough architecture quality that additional maintenance jobs can reuse the same runtime later.
- Produce a final report that a human reviewer can audit without reading the full trace.

### X-ARC Release Goals

PatchPilot v1 must visibly satisfy all five assignment requirements:

1. **50+ typed tools across 4+ namespaces.**
2. **At least one real subagent with isolated context and scoped tools.**
3. **Long-horizon execution over at least 20 tool calls in a single session.**
4. **Production scaffolding:** observability, retries, rate limits, typed errors, tests, and evals.
5. **Composable tool I/O** where structured output from one tool feeds another tool.

### Reliability Goal

Python repositories using pytest are the first deeply supported path. Other stacks can enter the same orchestration through a generic `--test-command` path, but v1 should not claim equal repair reliability outside Python/pytest.

## 6. Non-Goals

PatchPilot v1 will not:

- Become a general-purpose coding agent.
- Optimize for arbitrary feature implementation.
- Open pull requests automatically.
- Integrate with hosted CI providers.
- Support every language equally.
- Run unbounded shell commands without permission flags, risk classification, tracing, timeouts, and budgets.
- Depend on a single hard-coded model provider.
- Hide context management inside prompts only.
- Fork, wrap, or repackage OpenHands, SWE-agent, Aider, or another existing coding agent as the core product.

## 7. Core Use Case

### Fixture Demo Task

Command:

```bash
patchpilot run --repo ./fixtures/buggy-python-repo --goal "Fix the failing test and explain the root cause" --allow-exec --allow-write
```

Expected behavior:

1. Create a session ID and trace ID.
2. Inspect repository structure and git state.
3. Detect language, package manager, and test command.
4. Run tests and capture failure output.
5. Extract failure locations and related symbols.
6. Read relevant source and test files.
7. Spawn `DiagnosisAgent` with scoped read-only tools.
8. Receive a structured diagnosis result.
9. Classify the task as `source_fix`, `test_repair`, `config_fix`, `dependency_fix`, `mixed`, or `unsupported`.
10. Build a typed patch plan from evidence.
11. Validate patch shape and permissions before any write.
12. Apply the patch.
13. Run targeted tests.
14. If validation fails, inspect the new failure and iterate within budget.
15. Run broader tests after targeted validation passes.
16. Capture git diff.
17. Spawn `ReviewAgent` with scoped read-only diff and test tools.
18. Receive a structured review result.
19. Apply a small review correction only when justified and within policy.
20. Produce the final structured report.
21. Export the session trace.

The fixture run must contain at least 20 tool calls.

### Real Local Repo Task

Command:

```bash
patchpilot run --repo ./cloned-open-source-repo --goal "Fix the failing test and explain the root cause" --test-command "pytest" --allow-exec --allow-write
```

Expected behavior:

- Inspect a real cloned local repository.
- Use a supplied or detected test command.
- Run the same investigate, patch, validate, review, and report loop.
- Record the same structured trace format used by fixture runs.
- Return `success`, `partial`, or `failed` based on validation and budget outcomes.

The real-repo path is a product credibility path, not the primary assignment gate. The fixture path must be deterministic and reliable first.

## 8. User Experience

PatchPilot is delivered as a CLI.

Required commands:

```bash
patchpilot run --repo <path> --goal <goal>
patchpilot tools list
patchpilot trace show <trace_id>
patchpilot eval --suite <suite_name>
```

Useful optional commands:

```bash
patchpilot config show
patchpilot fixtures list
patchpilot report show <trace_id>
```

The CLI should print concise progress updates:

```text
[tr_abc123] inspecting repo
[tr_abc123] running tests
[tr_abc123] diagnosis subagent completed: confidence=0.82
[tr_abc123] patch plan validated
[tr_abc123] patch applied
[tr_abc123] targeted tests passed
[tr_abc123] review approved
```

The final output should include:

- Final status.
- Root cause.
- Task classification.
- Files changed.
- Tests run.
- Review outcome.
- Risks.
- Trace path.

## 9. Model Provider Requirements

PatchPilot uses OpenRouter as the live model gateway.

Environment variables:

```text
OPENROUTER_API_KEY=...
PATCHPILOT_MODEL=anthropic/claude-sonnet-4.5
PATCHPILOT_BASE_URL=https://openrouter.ai/api/v1
```

Model requirements:

- Model provider must be configurable.
- The code must expose a model client interface.
- Live runs use `OpenRouterModelClient`.
- Unit, integration, and eval tests use `FakeModelClient`.
- The runtime must support retries, rate limits, typed model errors, and structured model responses.
- Model calls must be traced with duration, status, retry metadata, and relevant request/response shape.

OpenRouter is used to preserve model flexibility without changing the agent architecture.

## 10. Key Product Decisions

- **Failing-test repair is the v1 wedge.** It gives the product a clear trigger, measurable outcome, and strong assignment fit.
- **X-ARC criteria are release gates.** The product can be broader in architecture, but v1 does not ship unless the assignment-visible proof is present.
- **Python/pytest is first-class for v1.** The core loop stays language-agnostic, but reliability claims focus on the first adapter.
- **Subagents are product behavior, not decoration.** Diagnosis and review must run through isolated subagent loops with scoped tools and structured results.
- **Patch planning precedes writes.** PatchPilot must not write files until a typed patch plan is produced and validated.
- **Deterministic evals are mandatory.** Live model demos can be useful, but the submission must pass through `FakeModelClient` and fixture-based evals.
- **Existing agent frameworks are references only.** LangGraph can provide graph execution, but PatchPilot owns the registry, tool contracts, context strategy, subagent contracts, eval harness, and traces.

## 11. Functional Requirements

### FR1: Tool Registry

PatchPilot must provide a coherent typed registry of at least 50 tools across at least 4 namespaces.

Minimum namespaces:

- `fs`
- `git`
- `code`
- `exec`
- `memory_eval`
- `subagent`

Each tool must define:

- Name.
- Namespace.
- Description.
- Input schema.
- Output schema.
- Permission level.
- Retry policy.
- Rate-limit policy.
- Handler reference.

Acceptance criteria:

- `patchpilot tools list` returns at least 50 tools.
- Tools are grouped by namespace.
- Tests verify that all tools have valid schemas.
- Tool dispatch uses registry lookup by tool name and registered handler reference.
- Tool dispatch does not rely on a giant phase-specific conditional chain.
- Tests fail if duplicate tool names exist, schemas are missing, handlers are missing, registered tool count is below 50, or namespace count is below 4.

### FR2: Model-Driven Tool Selection

The model must choose tools from registry metadata rather than through hard-coded task routing.

PatchPilot may enforce a fixed high-level lifecycle:

```text
inspect -> reproduce -> diagnose -> plan_patch -> apply_patch -> validate -> review -> report
```

Within each phase, the runtime filters the registry to tools allowed for that phase, then the model selects the next tool call from the available tool metadata.

Acceptance criteria:

- The agent presents tool names, descriptions, permissions, and schemas to the model.
- The model returns a structured tool call request.
- The `ToolExecutor` validates and executes the requested tool.
- Invalid tool calls produce typed errors and trace events.
- Trace output records explicit `model.tool_selection` events before tool execution.
- Tests verify that phase filtering does not bypass registry-based tool selection.
- Tests verify that selected tools are resolved through the `ToolRegistry`, not through phase-specific conditional dispatch.

### FR3: Subagent Orchestration

PatchPilot must include real subagents with isolated context and scoped tools.

Required subagents:

- `DiagnosisAgent`
- `ReviewAgent`

Optional stretch subagent:

- `TestPlannerAgent`

Implementation model:

- One shared `SubagentRuntime`.
- Separate typed configs for each subagent.
- Each config defines prompt, input schema, output schema, allowed tools, permission level, and budgets.

Acceptance criteria:

- Parent agent spawns a subagent through a dedicated subagent tool.
- Subagent receives task-specific context, not the full parent transcript.
- Subagent receives only a scoped subset of tools.
- Subagent runs its own model/tool loop.
- Subagent returns a Pydantic-validated structured result.
- Trace logs show subagent start, tool calls, result, and return to parent.

### FR4: Long-Horizon Execution

PatchPilot must complete a single task that spans at least 20 tool calls without losing plan coherence.

Acceptance criteria:

- Demo trace contains at least 20 tool call records.
- Trace contains `plan.updated` events at phase transitions.
- Session state includes plan, current step, observations, artifacts, subagent results, memory summary, budgets, and final report.
- Context compaction is implemented in code.
- Final report references the original goal, diagnosis, patch, tests, review, and risks.
- Eval checks that the observed phase order remains coherent.

### FR5: Context Management

PatchPilot must maintain explicit session state.

State fields:

- `goal`
- `plan`
- `current_step`
- `observations`
- `tool_call_history`
- `artifacts`
- `subagent_results`
- `memory_summary`
- `budgets`
- `final_report`

Compaction requirements:

- Use phase-boundary compaction after inspect, reproduce, diagnose, validate, and review.
- Use budget-triggered compaction when context or tool-output budgets approach configured limits.
- Keep recent tool calls verbatim.
- Summarize older observations.
- Preserve structured artifacts and subagent outputs.
- Preserve current plan, open risks, and test results.
- Preserve important artifacts exactly, including `TestResult`, `DiagnosisResult`, `PatchPlan`, `PatchValidation`, `PatchApplyResult`, `ReviewResult`, final diff, and open risks.
- Build repo-map style summaries instead of loading whole repositories into context.
- Use subagents to isolate bulky investigation and return compact structured summaries to the parent.

Acceptance criteria:

- Unit tests cover context compaction.
- Integration trace shows at least one state update path.
- Trace output records explicit `context.compacted` events with compaction reason, preserved artifacts, and summarized observation count.

### FR6: Composable Tool I/O

At least one tool must consume the structured output of another tool.

Required chain:

```text
code.search_text -> fs.read_files -> DiagnosisAgent -> PatchPlan -> code.validate_patch_shape -> fs.apply_patch -> exec.run_targeted_test -> ReviewAgent -> FinalReport
```

Acceptance criteria:

- Schemas represent each intermediate artifact.
- Tests verify that output from one tool can be passed as input to another.
- Final trace includes at least one composed chain.

### FR7: Iterative Repair Loop

PatchPilot must keep repairing until success or budget exhaustion.

Default termination conditions:

- Targeted and full validation pass.
- Maximum repair attempts reached.
- Maximum tool calls reached.
- Maximum model calls reached.
- Maximum diff size exceeded.
- Failure is classified as unsupported.

Default budgets:

```text
max_repair_attempts = 3
max_tool_calls = 80
max_model_calls = 20
max_diff_lines = 200
```

Acceptance criteria:

- Failed validation causes the agent to inspect the new error before another patch.
- Final report records each attempt.
- Final status is one of `success`, `partial`, or `failed`.

### FR8: Task Classification And Edit Policy

Before applying a patch, PatchPilot must classify the task.

Task classes:

- `source_fix`
- `test_repair`
- `config_fix`
- `dependency_fix`
- `mixed`
- `unsupported`

Patch policy:

- PatchPilot may edit source, tests, or config when justified by evidence.
- PatchPilot must not change tests merely to make the suite pass.
- Test edits are allowed when the user asked for test repair/test creation or when evidence shows the test is stale, incomplete, incorrectly written, or inconsistent with documented behavior.
- Every changed file must be classified by change type and justified in the final report.

Acceptance criteria:

- Patch plans include a task classification.
- Patch plans include allowed file categories.
- Final report explains why tests were edited if any test files changed.
- `ReviewAgent` checks whether test edits are justified.

### FR9: Patch Planning Before Writes

PatchPilot must generate and validate a typed patch plan before any file write.

Required flow:

```text
DiagnosisResult -> PatchPlan -> PatchValidation -> PatchApplyResult
```

The patch plan must include:

- Task classification.
- Files intended to change.
- Change type per file.
- Evidence IDs supporting each edit.
- Expected validation commands.
- Patch constraints such as max diff lines and protected paths.

Acceptance criteria:

- No write-capable tool runs without a valid `PatchPlan`.
- `code.validate_patch_shape` runs before `fs.apply_patch`.
- Invalid patch plans produce typed errors and trace events.
- Final report includes patch plan summary and validation outcome.

### FR10: Stack Adapter Interface

PatchPilot must separate the language-agnostic repair loop from stack-specific detection and validation.

Required adapter responsibilities:

- Detect whether the adapter applies to a repo.
- Identify package/test configuration.
- Propose targeted and full test commands.
- Parse common failure output into structured failure locations.
- Map test failures to likely source files.

Required v1 adapters:

- `PythonPytestAdapter`: first-class adapter for Python repositories using pytest.
- `GenericCommandAdapter`: fallback adapter when the user supplies `--test-command`.

Optional stretch adapters:

- `NodePackageAdapter`.
- `GoTestAdapter`.

Acceptance criteria:

- The parent repair loop does not hard-code Python-only behavior.
- Python/pytest tests verify deep adapter behavior.
- A generic command fixture proves that non-Python or adapter-unknown repos can enter the same orchestration path when a test command is provided.

### FR11: Production Scaffolding

PatchPilot must include production-oriented runtime pieces.

Required:

- Structured JSONL traces.
- Trace IDs and session IDs.
- Retries with exponential backoff.
- Rate limiting.
- Typed errors.
- Unit tests.
- Integration tests.
- Eval harness.

Acceptance criteria:

- Tests cover registry, schemas, errors, retries, rate limits, context compaction, and command risk classification.
- Integration test runs one fixture task end to end.
- Eval command scores a fixture run.
- Trace output contains tool, model, subagent, context, retry, and error events with duration and status.

### FR12: Evaluation Harness

PatchPilot must ship with a deterministic eval path.

Eval should check:

- Did the agent call at least 20 tools?
- Did it spawn a subagent?
- Did the trace include `plan.updated` events?
- Did phase order remain coherent?
- Did tests pass after patching?
- Did the final report include root cause, changed files, tests, and risks?
- Did it avoid unauthorized tools?
- Did it preserve structured trace output?

Acceptance criteria:

- `patchpilot eval --suite smoke` runs successfully.
- Eval result is emitted as JSON.
- Eval can run with `FakeModelClient`.
- The smoke suite is suitable for the X-ARC submission without live model access.

## 12. Required Tool Inventory

PatchPilot v1 should start with these 62 tools. The count is intentionally above the 50-tool assignment floor so the release is not fragile.

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

### subagent

- `subagent.spawn_diagnosis`
- `subagent.spawn_review`
- `subagent.spawn_test_planner`
- `subagent.list_available`
- `subagent.get_result`

## 13. Structured Outputs

### Final Report

The final report must be JSON-serializable.

```json
{
  "goal": "string",
  "status": "success|partial|failed",
  "task_classification": "source_fix|test_repair|config_fix|dependency_fix|mixed|unsupported",
  "root_cause": "string",
  "patch_plan": {
    "status": "valid|invalid|skipped",
    "summary": "string"
  },
  "changed_files": [
    {
      "path": "string",
      "change_type": "source_fix|test_repair|config_fix|dependency_fix|review_fix",
      "justification": "string"
    }
  ],
  "attempts": [
    {
      "attempt": 1,
      "result": "passed|failed",
      "summary": "string"
    }
  ],
  "tests_run": [
    {
      "command": "string",
      "exit_code": 0,
      "status": "passed|failed"
    }
  ],
  "subagents": [
    {
      "name": "string",
      "status": "success|failed"
    }
  ],
  "risks": ["string"],
  "trace_id": "string"
}
```

### Trace Event

```json
{
  "trace_id": "string",
  "session_id": "string",
  "event_type": "tool.started|tool.completed|model.called|model.tool_selection|plan.updated|subagent.started|subagent.completed|context.compacted|retry|rate_limit.wait|error",
  "name": "string",
  "duration_ms": 0,
  "status": "success|failed",
  "payload": {}
}
```

### Plan Update Event

```json
{
  "trace_id": "string",
  "session_id": "string",
  "event_type": "plan.updated",
  "phase": "inspect|reproduce|diagnose|plan_patch|apply_patch|validate|review|report",
  "current_step": "string",
  "remaining_steps": ["string"],
  "reason": "string"
}
```

Expected phase order:

```text
inspect -> reproduce -> diagnose -> plan_patch -> apply_patch -> validate -> review -> report
```

## 14. Technical Architecture

The architecture should stay product-shaped while prioritizing the assignment-critical pieces.

```text
patchpilot/
  cli.py
  config.py
  models/
    base.py
    openrouter.py
    fake.py
  runtime/
    graph.py
    state.py
    context.py
    subagents.py
  adapters/
    base.py
    python_pytest.py
    generic_command.py
    node_package.py
    go_test.py
  tools/
    registry.py
    executor.py
    fs.py
    git.py
    code.py
    exec.py
    memory_eval.py
    subagent.py
  schemas/
    common.py
    tool_io.py
    reports.py
  observability/
    tracing.py
    logging.py
  evals/
    harness.py
    suites.py
tests/
fixtures/
```

Architecture responsibilities:

- CLI owns user input, config loading, and command presentation.
- Parent runtime owns phase order, state transitions, budget checks, and final report generation.
- Tool registry owns tool metadata, schemas, handlers, permissions, retry policy, and rate limits.
- Tool executor owns validation, execution, tracing, retries, and permission enforcement.
- Subagent runtime owns isolated contexts and structured subagent loops.
- Adapters own stack-specific detection, failure parsing, and validation command selection.
- Trace store owns JSONL persistence and trace lookup.
- Eval harness owns deterministic scoring of trace and report properties.

## 15. Observability

PatchPilot must write JSONL traces under:

```text
.patchpilot/traces/<trace_id>.jsonl
```

Trace events must include:

- Tool calls.
- Model calls.
- Model tool selections.
- Subagent lifecycle and child spans.
- Plan updates.
- Context compaction.
- Retry attempts.
- Rate-limit waits.
- Command execution details.
- Errors.
- Final report.

Command execution trace payloads must include stdout, stderr, exit code, duration, timeout status, working directory, and risk class.

## 16. Safety and Permissions

PatchPilot should treat tools as permissioned capabilities.

Permission levels:

- `read`: inspect files, git state, test output, and structured artifacts.
- `write`: edit files or apply patches.
- `exec`: run local commands.
- `external`: call models or remote services.

Subagents receive the minimum permissions needed.

`DiagnosisAgent` and `ReviewAgent` should be read-only by default.

### Command Execution Policy

PatchPilot is allowed to run repo-relevant local commands needed for diagnosis or repair when execution is enabled.

Required CLI flags:

```text
--allow-exec
--allow-write
--allow-high-risk-exec
```

Command risk classes:

- `low`: test, lint, typecheck, formatting, and git inspection commands.
- `medium`: project dependency installation and project build commands.
- `high`: destructive commands, commands that push to remotes, commands that modify files outside the repo, shell pipelines that execute remote scripts, or permission-changing commands.

Allowed with `--allow-exec`:

- `pytest`
- `python -m pytest`
- `ruff check`
- `mypy`
- `npm test`
- `pnpm test`
- `go test ./...`
- `pip install -e .`
- `pip install -r requirements.txt`
- `poetry install`
- `uv sync`
- `npm install`
- `pnpm install`
- `go mod download`
- `make test`

High-risk commands require `--allow-high-risk-exec`.

All command execution must:

- Run from inside the target repository.
- Be recorded in the trace.
- Have a timeout.
- Count against execution budgets.
- Capture stdout, stderr, exit code, duration, and risk class.
- Be summarized in the final report when it affects the repair loop.

Dependency installation policy:

- Dependency installation belongs to setup or reproduction.
- PatchPilot may run one detected or selected dependency installation sequence when dependencies appear missing and `--allow-exec` is enabled.
- Dependency installation must not repeat inside every repair attempt.
- If dependencies remain unavailable after the bounded setup attempt, PatchPilot should return `partial` or `failed` with missing dependency evidence.

## 17. Success Metrics

### X-ARC Release Metrics

The v1 release is successful when:

- `patchpilot tools list` shows at least 50 tools across at least 4 namespaces.
- Demo trace contains at least 20 tool calls.
- Demo trace contains at least one `DiagnosisAgent` invocation and one `ReviewAgent` invocation.
- At least one structured tool output is consumed by another tool.
- Integration fixture passes after the agent run.
- Python/pytest adapter completes the full repair path reliably.
- Generic test-command path can run the same orchestration flow on a non-Python or adapter-unknown repo.
- Test suite passes.
- `patchpilot eval --suite smoke` returns passing JSON with `FakeModelClient`.
- `MEMO.md` explains what was built, what was cut, future work, and one defended design decision.

### Product v1 Metrics

The product shape is credible when:

- A human can understand the final report without opening the trace.
- A reviewer can audit the trace and see why each patch was attempted.
- Failed runs end with useful evidence and risks rather than silent failure.
- The runtime can add another maintenance job later without replacing the registry, state, subagent, trace, or eval architecture.

## 18. Five-Day Milestones

### Day 1: Foundation

- Python project scaffold.
- Typer CLI.
- Config loading.
- OpenRouter model client.
- Fake model client.
- Tool registry skeleton.
- Initial fs, git, and code tools.

### Day 2: Tool System And Safety

- Complete 62 tool definitions.
- Add schemas for tool inputs and outputs.
- Add executor with validation, retries, rate limits, permissions, and tracing.
- Add command risk classification.
- Add stack adapter interface.
- Add Python/pytest adapter.
- Add generic test-command adapter.
- Add registry, schema, and executor tests.

### Day 3: Agent Runtime

- Parent repair lifecycle.
- Session state.
- Context compaction.
- Model-driven tool selection.
- `DiagnosisAgent`.
- `ReviewAgent`.
- Subagent tests.

### Day 4: Eval And Demo

- Fixture repo.
- Full repair loop.
- Deterministic fake-model path.
- Real cloned repo smoke run with `--allow-exec --allow-write`.
- Eval harness.
- Integration test.
- 20+ tool-call trace.

### Day 5: Polish And Submission

- `MEMO.md`.
- README.
- CLI polish.
- Test and eval run.
- Video walkthrough.
- Codex session export.
- Public GitHub push.

## 19. Open-Source References

References are for architecture study only, not direct forking.

- LangGraph: stateful agent/workflow execution substrate.
  - https://github.com/langchain-ai/langgraph
- Deep Agents: subagent patterns, planning, filesystem-style state, and long-horizon task flow.
  - https://github.com/langchain-ai/deepagents
- langgraph-bigtool: scalable tool registry and large tool-selection patterns.
  - https://github.com/langchain-ai/langgraph-bigtool
- OpenHands: software agent runtime, sandboxing ideas, event streams, and coding-agent ergonomics.
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

## 20. Risks

### Risk: Product V1 Drifts Into Generic Coding Agent

Mitigation:

Keep failing-test repair as the v1 wedge. Name broader maintenance tasks as future product directions, not release requirements.

### Risk: Assignment Requirements Become Checkbox Features

Mitigation:

Make each assignment property load-bearing in the repair loop: tools are used for real actions, subagents diagnose and review, traces drive evals, and composed outputs feed later steps.

### Risk: 50+ Tools Become Superficial

Mitigation:

Every tool must be typed, registered, permissioned, traceable, and executable through the same registry/executor path. Tests enforce schemas, handlers, counts, and namespaces.

### Risk: Live Model Calls Are Expensive Or Flaky

Mitigation:

Use OpenRouter for live flexibility, but make the submission path deterministic with `FakeModelClient`, fixture repos, retry budgets, and evals.

### Risk: Demo Fails During Recording

Mitigation:

Use a deterministic fixture and smoke eval as the release gate. Treat live model runs as additional product proof, not the only proof.

### Risk: Language-Agnostic Claim Becomes Too Broad

Mitigation:

Implement the adapter boundary from the start, but state v1 reliability honestly: Python/pytest is first-class; generic command support is a fallback path.

### Risk: Unsafe Command Execution

Mitigation:

Require explicit execution and write flags, classify command risk, restrict execution to the target repo, trace every command, enforce timeouts, and require a separate high-risk flag.

## 21. MEMO.md Inputs

The eventual `MEMO.md` should cover:

- What was built: a failing-test repair agent with typed tools, subagents, traces, evals, and an auditable final report.
- What was cut: general coding tasks, PR creation, hosted CI integration, broad stack adapters, multi-repo memory, and fully hardened sandboxing.
- What more time would address: richer sandboxing, better repo maps, GitHub integration, broader eval suites, more stack adapters, and branch-review workflows.
- Defended decision: use LangGraph as the graph substrate while owning the assignment-critical registry, tool contracts, subagent isolation, context strategy, eval harness, and trace/report formats.

