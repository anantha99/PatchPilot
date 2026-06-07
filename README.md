# PatchPilot

PatchPilot is a repository repair agent for bounded maintenance loops. It inspects a local repo, reproduces failures, asks a real model to choose phase-scoped tools, delegates diagnosis and review to scoped subagents, creates a typed patch plan, validates the patch before writing, applies the patch, reruns tests, and emits an auditable JSON report plus JSONL trace.

The v2 focus is blind multi-file Python/pytest repair on small controlled repositories. The fixture repositories are controlled, but the runtime is not handed fixture answer keys: OpenRouter/MiniMax model calls, model-selected tools, inferred working sets, structured subagent outputs, structured-edit patch planning, file writes, retries, tests, and final report generation all run through PatchPilot.

## What v2 Can Do

- Repair a failing Python/pytest fixture repository through the real OpenRouter/MiniMax provider path.
- Use a MiniMax-only v2 model profile that defaults to `minimax/minimax-m3`; non-MiniMax model/profile values resolve back to the MiniMax default.
- Run phase-scoped tool selection across inspect, reproduce, diagnose, plan patch, apply patch, validate, review, and report.
- Spawn isolated diagnosis and review subagents with scoped tools and structured output schemas.
- Generate a typed `PatchPlan` with exact structured search/replace edits, then validate changed files, evidence links, protected paths, optional diff size, binary edits, ambiguous search blocks, and test edits before writes.
- Apply structured edits first, generate a clean local diff from the actual file changes, and rerun targeted plus full pytest validation, with budgeted retry when an applied patch fails validation.
- Preserve working-set, semantic-validation, attempt, retry, review, model usage, cost, cache, report, and trace artifacts.
- Score v2 fixture evals from persisted traces and final reports after the run. Product pass/fail is behavior-first: final tests pass, source edits are safe, semantic validation is visible, review does not reject, and the final report is complete. Fixture metadata is a post-run oracle diagnostic only and is excluded from the runtime work copy.

## Setup

Use Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

For live model runs, set an OpenRouter key. The CLI also reads `.env` when present.

```powershell
$env:OPENROUTER_API_KEY = "..."
```

Optional model configuration:

- `PATCHPILOT_MODEL` (MiniMax model IDs only)
- `PATCHPILOT_MODEL_PROFILE` (`v2-strong`, `minimax`, `minimax-m3`, or a direct MiniMax model id)
- `PATCHPILOT_V2_MODEL` (MiniMax model IDs only)
- `PATCHPILOT_BASE_URL`
- `PATCHPILOT_MODEL_PROVIDER`
- `PATCHPILOT_MAX_MODEL_CALLS`
- `PATCHPILOT_PROMPT_CACHE`

## Real Model Demo

Primary v1 demo:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli run `
  --repo fixtures\mock-store-python `
  --goal "Fix the failing pytest test" `
  --allow-exec `
  --allow-write `
  --model-provider openrouter `
  --model-profile v2-strong
```

The run prints a final JSON report to stdout and records the same report as a `run.completed` trace event under:

```text
fixtures/mock-store-python/.patchpilot/traces/
```

## Smoke Eval

Real OpenRouter smoke eval:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite smoke `
  --repo fixtures\mock-store-python `
  --model-provider openrouter `
  --model minimax/minimax-m3 `
  --live-eval
```

V2 multi-file live eval with visible progress:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite v2 `
  --repo fixtures `
  --model-provider openrouter `
  --model-profile v2-strong `
  --live-eval
```

Progress is written to stderr so stdout remains parseable JSON. Use `--quiet` for machine-only output.

Run one fixture at a time while tuning or inspecting failures:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli eval `
  --suite v2 `
  --repo fixtures\multifile-parser-validator `
  --model-provider openrouter `
  --model-profile v2-strong `
  --live-eval
```

Without `OPENROUTER_API_KEY`, the v2 eval returns categorized `missing_api_key` fixture results and does not spend model budget. Eval output includes `runtime_oracle_visible: false` to make the blind-runtime boundary explicit.

Live v2 eval also writes a Markdown report to:

```text
<eval-root>/.patchpilot/reports/report.md
```

The report includes product pass rate, multi-file contract match rate, per-fixture changed files, trace/report paths, test metadata, model calls, tool calls, retries, cost, cache, and oracle mismatch diagnostics.

## Offline Verification

Automated tests use deterministic fake or mocked model clients directly:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The fake provider is test infrastructure, not a product demo path. Product and live eval commands use `--model-provider openrouter`.

## Docker And Wrapper Commands

The PowerShell wrapper uses Docker Compose when available and falls back to the local `.venv`:

```powershell
.\scripts\xarc-test.ps1
.\scripts\xarc-test.ps1 -Target smoke
.\scripts\xarc-test.ps1 -Target live-eval
```

Direct Docker commands:

```bash
docker compose run --rm xarc-test
docker compose run --rm xarc-smoke
docker compose run --rm --env-file .env xarc-live-eval
docker compose run --rm xarc-shell
```

## Fixtures

- `fixtures/mock-store-python`: primary v1 demo repo. It contains a tiny ecommerce-style Python app where `apply_discount` subtracts the raw percent value instead of applying it as a percentage. The expected repair changes `mock_store/pricing.py`.
- `fixtures/buggy-python-repo`: deterministic arithmetic repair fixture used by direct fake-client tests.
- `fixtures/buggy-validation-repo`: validation branch fixture.
- `fixtures/buggy-parser-repo`: parser delimiter fixture with parametrized pytest failures.
- `fixtures/multifile-*`: eleven v2 multi-file Python/pytest fixture repos. Each fixture's pytest suite directly exercises behavior owned by every file listed in `expected_changed_source_files`, so known one-file partial repairs still fail and known full repairs pass. Eval uses `fixture.json` only after the run to emit `multi_file_contract` diagnostics; it is not copied into the runtime work repo.

## Trace Inspection

List tools:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli tools list
```

Show a trace:

```powershell
.\.venv\Scripts\python.exe -m patchpilot.cli trace show tr_fd1f59f76f87 --trace-dir fixtures\mock-store-python\.patchpilot\traces
```

Traces include `model.tool_selection`, `tool.started`, `tool.completed`, `subagent.started`, `subagent.completed`, `model.patch_plan`, `runtime.repair_attempt`, `runtime.retry_scheduled`, `plan.updated`, `context.compacted`, and `run.completed` events. Final JSON reports are written beside traces under `.patchpilot/reports/`.
