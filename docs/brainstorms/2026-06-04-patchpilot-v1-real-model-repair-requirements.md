---
date: 2026-06-04
topic: patchpilot-v1-real-model-repair
---

# PatchPilot V1 Real Model Repair Requirements

## Summary

PatchPilot v1 should be a real GLM-driven Python/pytest repair agent, not a deterministic demo path. It should use OpenRouter with GLM-4.7 Flash for product runs and eval runs, while preserving mocked models only for automated tests.

---

## Problem Frame

`assignment.md` asks for a production-shaped autonomous agent where depth matters more than complete breadth. The current v0 proves the skeleton: tool registry, traces, safety gates, evals, and a fixture repair path. For the final submission, the product should visibly repair failures through a real model-driven loop, with architecture and traces proving that the model selected tools, subagents performed isolated work, and tool outputs composed into later decisions.

The old `PRD.md` should be treated as the v0/Vebo proof document. The v1 source of truth is the actual assignment brief in `assignment.md` plus this requirements document.

---

## Key Decisions

- **Real model path is the product path.** Normal `patchpilot run` should use OpenRouter with GLM-4.7 Flash. Fake or mocked model clients remain test infrastructure, not the product experience.
- **Python/pytest is the reliability wedge.** v1 should make strong claims only for Python/pytest repair. Generic command support may remain, but it should not dilute the Python path.
- **Model reasoning, tool-verified evidence.** GLM should drive diagnosis, patch planning, tool selection, review, and retry choices. Tools still execute and verify concrete facts: file reads, test results, diffs, patch application, permissions, and traces.
- **Assignment proof is load-bearing.** The five assignment properties should appear in the actual repair flow, not as side demos or isolated unit tests.
- **Budget is managed, not avoided.** GLM calls are allowed, but v1 should track model calls, token usage, estimated cost, and cache behavior so the user can see what the repair cost.

---

## Actors

- A1. **Developer user.** Runs PatchPilot on a local Python/pytest repository with a failing test and reviews the final report.
- A2. **Parent repair agent.** Owns phase order, context strategy, tool registry filtering, permissions, retries, and final reporting.
- A3. **GLM-4.7 Flash model.** Selects tools and returns structured decisions through OpenRouter.
- A4. **Diagnosis subagent.** Runs in an isolated context with scoped tools and returns structured root-cause evidence.
- A5. **Review subagent.** Runs in an isolated context with scoped diff/test tools and returns structured approval or issues.
- A6. **Assignment reviewer.** Reads the repository, commit history, traces, eval output, and `MEMO.md`.

---

## Key Flows

- F1. **Real model repair run**
  - **Trigger:** Developer runs PatchPilot against a local Python/pytest repo with `--allow-exec` and `--allow-write`.
  - **Actors:** A1, A2, A3, A4, A5.
  - **Steps:** Parent agent inspects the repo, reproduces the failure, asks GLM to choose evidence-gathering tools, spawns diagnosis, creates a patch plan, validates write safety, applies the patch, reruns tests, spawns review, and emits a final report.
  - **Outcome:** The failing test becomes passing or the run ends with a useful failed report and trace.

- F2. **Subagent diagnosis**
  - **Trigger:** Parent reaches diagnosis after reproducing a failure.
  - **Actors:** A2, A3, A4.
  - **Steps:** Parent spawns a diagnosis subagent with scoped read/search/test-output tools. The subagent runs its own model/tool loop and returns typed root cause, evidence, recommendation, confidence, and risks.
  - **Outcome:** Parent consumes the subagent result as structured input to patch planning.

- F3. **Subagent review**
  - **Trigger:** Parent has applied a patch and run validation.
  - **Actors:** A2, A3, A5.
  - **Steps:** Parent spawns a review subagent with scoped diff/test/report tools. The subagent checks the patch against evidence and validation results.
  - **Outcome:** Parent records approval or issues in the final report and trace.

- F4. **Eval and submission proof**
  - **Trigger:** Developer or reviewer runs the eval suite.
  - **Actors:** A1, A6.
  - **Steps:** Eval reads persisted traces and reports, then scores model-driven tool selection, 20+ tool calls, subagent isolation, phase coherence, production scaffolding, composable tool I/O, and final repair result.
  - **Outcome:** Eval emits JSON that a reviewer can audit without relying on private runtime state.

---

## Requirements

**Real Model Execution**

- R1. Normal product runs use OpenRouter with GLM-4.7 Flash as the default real model path.
- R2. Fake or mocked model clients are retained only for automated unit/integration tests; eval runs use the real OpenRouter/GLM path.
- R3. Model responses are structured and validated before use; invalid model output produces typed errors and trace events.
- R4. Model calls are traced with model name, phase, status, duration, retry metadata, token usage when available, and estimated cost when available.
- R5. Prompt caching is supported when OpenRouter/model/provider configuration allows it, and traces expose whether cache-related metadata was observed.

**Repair Capability**

- R6. PatchPilot repairs at least several Python/pytest fixture failures that differ in failure shape, not only one calculator-style bug.
- R7. The agent can inspect failure output, map tests to source, choose relevant files, and propose bounded patches from evidence.
- R8. PatchPilot validates patch plans before writes and refuses patches that escape repo boundaries, exceed limits, or touch protected paths.
- R9. Failed validation triggers a new evidence-gathering or retry decision rather than blindly reapplying patches.
- R10. Final reports accurately reflect changed files, tests run, attempts, root cause, risks, subagents, model used, and trace ID.

**Assignment Properties**

- R11. The registry exposes at least 50 typed tools across at least 4 namespaces, and model-selected tool execution resolves through the registry/executor path.
- R12. The parent run includes at least 20 tool calls in one coherent repair session.
- R13. At least one tool spawns a real isolated subagent that runs its own scoped model/tool loop and returns a typed result to the parent.
- R14. Context management is expressed in code through explicit state, phase views, compaction/summarization, and budgets.
- R15. At least one repair chain composes structured output from one tool into a later tool or model decision.

**Production Scaffolding**

- R16. External model calls use retry with exponential backoff and rate limits.
- R17. Local command execution remains permission-gated, timeout-bounded, risk-classified, and traceable.
- R18. Trace files persist model calls, tool calls, subagent spans, phase updates, errors, retries, rate-limit waits, and final reports.
- R19. Unit and integration tests cover registry integrity, model response validation, executor policy, command risk, patch safety, runtime failure handling, subagents, eval scoring, and at least one end-to-end real-model-compatible repair path.
- R20. `MEMO.md` is updated for final submission and explains what was built, what was cut, what additional time would address, and one defended design decision.

**Submission Readiness**

- R21. The repository can be made public without leaking secrets, local paths beyond normal traces, or API keys.
- R22. The walkthrough can demonstrate a real GLM-driven run, a substantive code path, and one moment where user/model direction diverged.
- R23. The submitted traces include Codex session export plus PatchPilot runtime traces for the demo/eval run.

---

## Acceptance Examples

- AE1. **Covers R1, R3, R4.** Given `OPENROUTER_API_KEY` is set, when `patchpilot run` starts, then the trace records GLM-4.7 Flash model calls and validated structured tool selections before tool execution.
- AE2. **Covers R6, R7, R8.** Given a Python fixture with a real failing pytest test, when PatchPilot runs with write/exec permissions, then it diagnoses evidence, creates a bounded patch plan, applies a source patch, and gets pytest passing.
- AE3. **Covers R9, R10.** Given the first patch fails validation, when PatchPilot continues, then it records the failed validation, gathers new evidence or revises the plan, and the final report includes the failed attempt.
- AE4. **Covers R13.** Given a reproduced failure, when diagnosis starts, then `subagent.spawn_diagnosis` creates an isolated child context, runs scoped model/tool calls, and returns typed evidence to the parent.
- AE5. **Covers R11, R12, R15.** Given a successful repair run, when the eval suite scores its trace, then it finds 50+ tools, 20+ tool calls, registry-mediated execution, and at least one structured tool-output chain.
- AE6. **Covers R16, R18, R23.** Given a model or tool error occurs, when the run ends, then traces include the error, retry/rate-limit context if applicable, and the final report is still JSON-serializable.

---

## Success Criteria

- The final submission demo shows a real GLM-driven repair path, not only a fake-model fixture.
- The deterministic/mocked test suite still runs without OpenRouter access, while eval runs require the real OpenRouter/GLM path.
- The live-model repair path is reliable enough for a three-to-five-minute walkthrough.
- Eval output proves the five assignment properties from traces and reports.
- The commit history shows meaningful progression from v0 proof to v1 product hardening.

---

## Scope Boundaries

**In scope for v1**

- Python/pytest repair as the primary product claim.
- GLM-4.7 Flash through OpenRouter for product runs.
- Real parent model loop and real diagnosis/review subagent model loops.
- Multiple Python fixture scenarios.
- Prompt caching support when provider metadata/configuration makes it available.
- Cost, token, and budget visibility.
- Strong final traces, eval output, `MEMO.md`, video-ready demo path, and Codex session export.

**Deferred for later**

- Broad Node/Go/Ruby adapters.
- PR creation and GitHub workflow automation.
- Hosted CI integration.
- Deep sandboxing beyond local repo boundaries, permissions, timeouts, and command risk policy.
- Multi-repo memory or long-term organizational knowledge.
- Full benchmark platform for comparing many models.

**Outside this product identity for v1**

- General-purpose coding assistant behavior.
- A notebook demo that works only because the script is hardcoded.
- A tool-count showcase where tools do not participate in the repair flow.

---

## Dependencies And Assumptions

- D1. OpenRouter access is available through `OPENROUTER_API_KEY`.
- D2. The selected model is `z-ai/glm-4.7-flash` unless explicitly changed.
- D3. Prompt caching support may vary by OpenRouter provider; v1 should expose observed cache metadata rather than promising savings.
- D4. The final demo repository should be small enough for GLM-4.7 Flash to reason over within budget and context limits.
- D5. Mocked models remain necessary for CI-style tests because live model calls are nondeterministic, network-dependent, and paid; they are not used as the final eval path.

---

## Sources And Research

- `assignment.md` is the source of truth for final submission requirements.
- `PRD.md` documents the earlier v0/Vebo proof framing and should not override the assignment brief.
- `README.md` and `MEMO.md` describe the current v0 implementation state and should be revised for final submission once v1 is built.
