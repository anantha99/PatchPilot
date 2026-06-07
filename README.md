# PatchPilot

PatchPilot is a production-shaped repository repair agent that fixes failing Python/pytest test suites. For now, it is focused on small Python repositories: the fix may be a single source-file change or a coordinated multi-file source change, but the validation target is still a failing pytest suite.

At a high level, PatchPilot inspects a local repo, reproduces the failure, asks an OpenRouter/MiniMax model to choose phase-scoped tools, delegates diagnosis and review to scoped subagents, creates a typed patch plan, validates the patch before writing, applies the patch, reruns tests, and writes an auditable JSON report plus JSONL trace.

The current product claim is deliberately narrow: PatchPilot repairs small controlled Python/pytest repositories, including v2 multi-file source bugs. It is not presented as a general coding assistant, arbitrary monorepo repair system, or test-generation tool.

## How To Use This Repo

Use this repo in three layers:

1. **Understand the product:** read this README, then `MEMO.md` for the assignment summary and `assignment.md` for the original X-ARC brief.
2. **Run PatchPilot locally:** create `.venv`, install with `pip install -e ".[dev]"`, set `OPENROUTER_API_KEY`, then run either a single repair or the v2 multi-file eval commands below.
3. **Inspect proof artifacts:** after a run, open the JSON report, JSONL trace, and optional Markdown eval report under `tmp/patchpilot-eval-work/...`.

The main source code is in `patchpilot/`, controlled target repos are in `fixtures/`, and automated tests are in `tests/`.

## Assignment Fit

PatchPilot is built for the X-ARC autonomous-agent assignment. The assignment asks for depth across five properties, and PatchPilot maps to them directly:

- **50+ tools across 4+ namespaces:** the registry exposes tools across `code`, `exec`, `fs`, `git`, `session`, and `subagent`.
- **Subagent orchestration:** diagnosis and review run as scoped child agents with bounded tool/model budgets and structured outputs.
- **Long-horizon execution:** the parent runtime moves through `inspect -> reproduce -> diagnose -> plan_patch -> apply_patch -> validate -> review -> report`.
- **Production scaffolding:** the code includes typed schemas, guarded execution, retries, rate limiting, trace events, reports, eval harnesses, and tests.
- **Composable tool I/O:** failure extraction, source mapping, diagnosis, patch planning, validation, patch application, tests, review, and final reporting all pass structured artifacts forward.

## What PatchPilot Does

- Runs a phase-gated repair loop over a local repo.
- Uses OpenRouter/MiniMax for model-selected tools and structured JSON outputs.
- Infers a working set from failing tests, source candidates, file reads, diagnosis output, and prior attempts.
- Uses diagnosis and review subagents that are read-only and scoped.
- Requires a typed `PatchPlan` before writes.
- Validates patch shape and semantics before `fs.apply_patch` can write.
- Rejects test edits for source-fix tasks, protected paths, repo escapes, ambiguous structured edits, undeclared files, oversized diffs, and under-evidenced multi-file plans.
- Records repair attempts and schedules retries when patch application or validation fails.
- Emits final JSON reports, trace JSONL, and v2 eval summaries.

## Repository Structure

```text
xarc/
  assignment.md              X-ARC assignment brief and submission requirements
  README.md                  This guide
  MEMO.md                    One-page assignment memo
  AGENTS.md                  Agent instructions and verification policy
  pyproject.toml             Python package metadata and dependencies
  scripts/xarc-test.ps1      Wrapper for repo verification
  patchpilot/                Main PatchPilot package
  fixtures/                  Controlled repair target repositories
  tests/                     Unit and integration tests
  docs/                      Requirements and implementation plans
  tmp/                       Local eval workspaces and reports
```

Important package areas:

```text
patchpilot/
  cli.py                     Typer CLI: run, eval, tools list, trace show
  config.py                  Runtime config, model profile, permission and budget settings
  runtime/graph.py           Parent repair loop and phase state machine
  runtime/subagents.py       Diagnosis/review subagent runtime and recovery behavior
  runtime/state.py           Session state, working set, attempts, rejected patch plans
  runtime/context.py         Context compaction for long runs
  tools/registry.py          Typed tool registry
  tools/executor.py          Tool execution with schema, policy, retry, rate-limit, tracing
  tools/code.py              Code inspection, source mapping, patch validation
  tools/fs.py                File operations and patch application
  tools/exec_tools.py        Test and command execution
  tools/session.py           Phase/artifact/session tools
  tools/subagent.py          Parent-facing subagent spawn tools
  schemas/tool_io.py         Tool input/output schemas, PatchPlan, DiagnosisResult, ReviewResult
  schemas/reports.py         Final report schema
  models/openrouter.py       OpenRouter client and metadata extraction
  evals/harness.py           Smoke and v2 multi-file eval runner/scoring
  evals/manifests/suites.json Fixture metadata used by eval after runtime finishes
  observability/tracing.py   JSONL trace store
```

## Setup Without Docker

Use Python 3.11+ from the repo root.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

For live model runs, set an OpenRouter key. The CLI also reads `.env` from the repo root when present.

```powershell
$env:OPENROUTER_API_KEY = "..."
```

Optional environment variables:

- `PATCHPILOT_MODEL_PROFILE` defaults to `v2-strong`.
- `PATCHPILOT_MODEL` accepts MiniMax model IDs.
- `PATCHPILOT_V2_MODEL` overrides the v2 profile model.
- `PATCHPILOT_BASE_URL` defaults to `https://openrouter.ai/api/v1`.
- `PATCHPILOT_MAX_MODEL_CALLS` limits model-call budget.
- `PATCHPILOT_PROMPT_CACHE=0` disables prompt-cache headers.

## Run A Single Repair

This runs PatchPilot directly against the mock store fixture and prints the final JSON report to stdout.

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli run `
  --repo fixtures\mock-store-python `
  --goal "Fix the failing pytest test" `
  --allow-exec `
  --allow-write `
  --model-provider openrouter `
  --model-profile v2-strong
```

Artifacts are written under the target repo:

```text
fixtures/mock-store-python/.patchpilot/traces/<trace_id>.jsonl
fixtures/mock-store-python/.patchpilot/reports/<trace_id>.json
```

## Run The V2 Multi-File Eval Without Docker

Run the full v2 multi-file suite:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite v2 `
  --repo fixtures `
  --model-provider openrouter `
  --model-profile v2-strong `
  --live-eval
```

Run one multi-file fixture while tuning or recording a focused demo:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite v2 `
  --repo fixtures\multifile-parser-validator `
  --model-provider openrouter `
  --model-profile v2-strong `
  --live-eval
```

Progress prints to stderr so stdout remains parseable JSON. Use `--quiet` if you only want machine-readable output:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite v2 `
  --repo fixtures\multifile-parser-validator `
  --model-provider openrouter `
  --model-profile v2-strong `
  --live-eval `
  --quiet
```

If `OPENROUTER_API_KEY` is missing, the v2 eval exits without spending model budget and returns categorized `missing_api_key` fixture results.

## Where Reports And Traces Go

V2 eval copies each fixture into a disposable blind workspace under:

```text
tmp/patchpilot-eval-work/v2-multifile/<fixture-name>/<run-id>/repo
```

For each fixture run, the eval JSON includes:

- `trace_id`
- `trace_path`
- `report_path`
- `work_repo`
- `changed_files`
- `tests_run`
- `model_calls`
- `tool_calls`
- `retry_count`
- `runtime_oracle_visible`
- `multi_file_contract`
- `oracle_diagnostics`

The final per-run artifacts are under the corresponding eval work root:

```text
tmp/patchpilot-eval-work/v2-multifile/<fixture-name>/<run-id>/traces/<trace_id>.jsonl
tmp/patchpilot-eval-work/v2-multifile/<fixture-name>/<run-id>/reports/<trace_id>.json
```

When `--live-eval` is used, PatchPilot also writes a Markdown suite report:

```text
tmp/patchpilot-eval-work/v2-multifile/reports/report.md
```

That report summarizes product pass rate, multi-file contract match rate, per-fixture status, changed files, trace paths, report paths, model calls, tool calls, retries, token/cost/cache metadata, and oracle diagnostics.

## Inspect A Trace

List registered tools:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli tools list
```

Show a trace:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli trace show <trace_id> --trace-dir tmp\patchpilot-eval-work\v2-multifile\<fixture-name>\<run-id>\traces
```

Useful trace events include:

- `model.tool_selection`
- `tool.started`
- `tool.completed`
- `subagent.started`
- `subagent.model.tool_selection`
- `subagent.model.structured_output`
- `subagent.completed`
- `model.patch_plan`
- `runtime.patch_plan_rejected`
- `runtime.repair_attempt`
- `runtime.retry_scheduled`
- `plan.updated`
- `context.compacted`
- `run.completed`

## Fixtures

Smoke fixtures:

- `fixtures/mock-store-python`: ecommerce pricing bug.
- `fixtures/buggy-python-repo`: arithmetic operator bug.
- `fixtures/buggy-parser-repo`: parser delimiter and whitespace bug.
- `fixtures/buggy-validation-repo`: inverted validation branch.

V2 multi-file fixtures:

- `fixtures/multifile-calendar-window`
- `fixtures/multifile-entitlement-ledger`
- `fixtures/multifile-inventory-state`
- `fixtures/multifile-parser-validator`
- `fixtures/multifile-permissions-contract`
- `fixtures/multifile-profile-contract`
- `fixtures/multifile-reexport-drift`
- `fixtures/multifile-retry-partial-trap`
- `fixtures/multifile-serialization-drift`
- `fixtures/multifile-shipping-rules`
- `fixtures/multifile-taxes-rounding`

The fixture repos are controlled, but the runtime work copy is blind. Eval metadata lives in `patchpilot/evals/manifests/suites.json` and is used after the run for scoring and diagnostics. The eval copy excludes `fixture.json`, `.patchpilot`, caches, virtualenvs, and other local artifacts.

## Offline Verification

Automated tests use mocked OpenRouter transports and deterministic fixtures so they do not spend model budget.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

You can also use the wrapper while forcing the local `.venv` path instead of Docker:

```powershell
.\scripts\xarc-test.ps1 -NoDocker -Target test
```

## Design Notes

PatchPilot keeps the parent runtime structured rather than fully open-ended. The model chooses tools inside each phase, but the phase machine keeps long-horizon repair coherent. The most important write boundary is:

```text
evidence -> typed PatchPlan -> semantic validation -> fs.apply_patch -> tests -> review -> report
```

The diagnosis subagent is intentionally resilient. If a model-selected read path is wrong or structured diagnosis fails, the subagent records the failure, gathers repo-grounded recovery context from tests/imports/source candidates, retries with constrained instructions, and can return a lower-confidence fallback diagnosis only when there is enough evidence. That keeps a single bad model response from ending the whole repair run.

The main v2 proof is not just "tests passed." A strong run should also show source-only edits, semantic validation, review not rejected, trace-visible model/tool/subagent activity, final report completeness, and a multi-file contract match in eval diagnostics.
