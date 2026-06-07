---
date: 2026-06-05
topic: patchpilot-v2-multifile-repair
---

# PatchPilot V2 Multi-File Repair Requirements

## Summary

PatchPilot v2 should move from a credible single-source repair demo to a materially stronger repair agent for generalized multi-file Python/pytest source bugs. The v2 bar is repair power: PatchPilot should handle coordinated source changes across multiple files, retry when validation fails, and prove the capability across a varied fixture suite using the strongest configured real OpenRouter model.

The mocked product repositories remain synthetic and controlled. The agent behavior should remain real: live model calls, model-selected tools, scoped subagents, typed patch planning, patch validation, writes, retries, tests, review, traces, and final reports.

---

## Problem Frame

PatchPilot v1 proves that the architecture can run a real model-driven repair loop on a small Python fixture: inspect, reproduce, diagnose, plan, patch, validate, review, and report. The next useful step is not broader language support or PR automation. It is making the repair loop more capable when the correct fix spans multiple source files and the first attempt may fail.

The v2 product should answer a sharper question: can PatchPilot repair harder Python/pytest bugs without overfitting one fixture? A successful v2 should show the model can gather enough evidence, keep context coherent, produce a multi-file patch plan, validate that every file edit serves the same root cause, and iterate when tests reject the patch.

---

## Key Decisions

- **Repair power is the primary v2 bar.** Eval credibility and architecture polish matter, but they serve the main goal: harder real repairs.
- **Generalized multi-file source repair is the flagship capability.** The suite should include shared utility bugs, contract drift, and coordinated business behavior, but the product claim is one generalized capability rather than three separate tracks.
- **The proof bar is a varied suite, not a hand-picked demo.** v2 should run against 10+ multi-file Python/pytest fixtures and target a 90% live pass rate.
- **Use the best real OpenRouter model for the v2 claim.** MiniMax M3 stays configurable, but v2 should optimize for the strongest model available through the same provider path.
- **Retries are a first-class repair behavior.** Validation failure should trigger a budgeted retry loop, not a one-off failure or blind reapplication.
- **Patch plans are hybrid and typed.** The model should return structured per-file edits plus a unified multi-file diff; PatchPilot should cross-check them before applying.
- **Validation is semantic, not just syntactic.** Every changed file must be safe, evidence-linked, and necessary for the same diagnosed root cause.
- **Context packing is artifact-aware.** Typed artifacts remain lossless; bulky command/file output is summarized into a compact working set.
- **Prompt caching starts with stable prompt layers.** Stable system/tool/schema/phase content should be separated from volatile run state, and cache metadata should always be recorded when returned.
- **Review is bounded but meaningful.** The review subagent checks correctness, necessity, and regression risk inside fixed tool/model budgets.

---

## Actors

- A1. **Developer user.** Runs PatchPilot against a local Python/pytest repo or fixture suite and reviews the final report.
- A2. **Parent repair agent.** Owns phase order, budgets, retry policy, artifact-aware context, patch validation, write safety, and final reporting.
- A3. **OpenRouter model.** Selects tools and returns structured diagnosis, patch-plan, retry, and review inputs through the configured model path.
- A4. **Diagnosis subagent.** Runs scoped tools and returns root cause, implicated files, evidence, confidence, risks, and recommended repair direction.
- A5. **Review subagent.** Reviews final or attempted patches for correctness, file necessity, regression risk, and missing validation.
- A6. **Eval runner.** Runs 10+ fixtures, scores aggregate pass rate, and reports repair/trace quality.
- A7. **Assignment reviewer.** Inspects repo, README, traces, eval output, and memo to verify the v2 claim.

---

## Key Flows

- F1. **Generalized multi-file repair**
  - **Trigger:** Developer runs PatchPilot on a Python/pytest repo where failures point to a source bug spanning multiple files.
  - **Steps:** Parent agent inspects structure, reproduces pytest failure, gathers evidence across tests and source files, spawns diagnosis, builds a working set, requests a hybrid multi-file patch plan, validates semantic necessity, applies the patch, runs targeted and full tests, spawns review, and emits a final report.
  - **Outcome:** Tests pass with a source-only multi-file patch, or the run fails with a traceable explanation and preserved artifacts.

- F2. **Validation-failure retry**
  - **Trigger:** A patch applies but targeted or full pytest validation fails.
  - **Steps:** Parent records the failed attempt, preserves the patch plan and validation output, compacts context into a retry working set, asks the model for the next repair decision, gathers any missing evidence, and attempts a revised patch while budgets remain.
  - **Outcome:** PatchPilot converges to a passing repair or exits after budget exhaustion with every attempt, test result, and rationale in the final report.

- F3. **Semantic patch validation**
  - **Trigger:** The model returns a hybrid patch plan.
  - **Steps:** PatchPilot checks source-only writes, protected paths, undeclared files, diff size, structured edits versus unified diff consistency, evidence links for every changed file, and whether each edit serves the same root cause.
  - **Outcome:** Safe coherent plans proceed to write; incoherent or under-evidenced plans are rejected or sent through retry/evidence gathering.

- F4. **Artifact-aware context update**
  - **Trigger:** Tool history grows, validation fails, or the agent transitions into patch planning/retry/review.
  - **Steps:** PatchPilot preserves typed artifacts losslessly, summarizes bulky command/file outputs, tracks current working set files, and exposes compact phase-appropriate context to parent and subagents.
  - **Outcome:** Models see enough context to repair without drowning in raw trace data or losing critical artifacts.

- F5. **Multi-fixture live eval**
  - **Trigger:** Developer runs the v2 eval suite.
  - **Steps:** Eval copies each fixture into disposable workspaces, runs live OpenRouter repair, scores pass/fail plus trace properties, aggregates pass rate, and records failure categories.
  - **Outcome:** v2 reports aggregate repair power across varied multi-file fixtures, with a target of at least 90% live pass rate.

---

## Requirements

**Multi-File Repair Capability**

- R1. PatchPilot repairs generalized multi-file Python/pytest source bugs where the correct fix spans at least two source files.
- R2. The fixture suite includes at least 10 varied multi-file Python/pytest repos.
- R3. The suite includes multiple bug shapes, including shared utility bugs, contract drift, and coordinated behavior changes.
- R4. The v2 live eval target is at least 90% pass rate across the multi-file fixture suite.
- R5. Failed fixtures must be categorized with traceable failure reasons, not only counted as pass/fail.

**Model Path**

- R6. v2 uses the strongest configured real OpenRouter model for the main repair-power claim.
- R7. MiniMax remains supported as a configurable model path, but v2 is not constrained to MiniMax-only performance.
- R8. Parent repair, diagnosis, patch planning, retry decisions, and review all run through the same real model-provider abstraction.
- R9. Fake or scripted model behavior remains test infrastructure only.

**Hybrid Patch Planning**

- R10. Patch plans include structured per-file edits and a unified multi-file diff.
- R11. PatchPilot cross-checks structured edits against the unified diff before applying.
- R12. Patch plans identify expected changed files, root cause, evidence references, risk notes, and validation expectations.
- R13. PatchPilot rejects patch plans that edit tests for source-fix tasks unless a future task class explicitly allows test edits.
- R14. PatchPilot rejects protected paths, undeclared changed files, oversized diffs, and paths outside the repo.

**Semantic Validation**

- R15. Every changed file must be evidence-linked through diagnosis evidence, failure output, source/test mapping, imports, or read file context.
- R16. Every changed file must be judged necessary for the same diagnosed root cause.
- R17. PatchPilot rejects or retries patches whose file edits appear to solve unrelated problems.
- R18. The final report records semantic validation outcomes, including rejected plans and reasons.

**Retry Loop**

- R19. When targeted or full validation fails after a patch attempt, PatchPilot enters a budgeted retry loop.
- R20. Retry attempts preserve prior diagnosis, patch plan, applied diff, validation output, and changed files.
- R21. Each retry can gather additional evidence before producing a revised patch.
- R22. Retry stops when tests pass, write/model/tool budgets are exhausted, or the model cannot produce a safe coherent patch.
- R23. Final reports include every attempt with patch summary, changed files, validation command, result, and failure reason.

**Context And Prompting**

- R24. Typed artifacts are preserved losslessly across compaction: diagnosis, patch plans, validation results, attempts, changed files, review outputs, command history, and model metadata.
- R25. Bulky outputs are summarized: long pytest output, large file reads, raw diffs, and repeated tool history.
- R26. The parent model sees a compact working set that includes relevant files, current hypothesis, validation state, prior attempts, and outstanding unknowns.
- R27. Subagents receive scoped context that is sufficient for their task without inheriting unrelated parent noise.
- R28. Prompt construction separates stable layers from volatile run state.
- R29. Stable layers include system instructions, schemas, tool metadata, and phase instructions.
- R30. Volatile layers include current phase, working set, recent outputs, attempts, and validation state.
- R31. Cache metadata is recorded whenever OpenRouter returns it.

**Subagents**

- R32. The diagnosis subagent can inspect multiple relevant files and return implicated files with evidence links.
- R33. The review subagent checks patch correctness, changed-file necessity, and regression risk.
- R34. Review runs within fixed tool/model budgets and does not become an unbounded repair loop.
- R35. Review output includes approval status, issues, evidence, missing validation, regression risk, and confidence.

**Eval And Reporting**

- R36. The v2 eval suite reports per-fixture result, aggregate pass rate, model used, cost metadata, model calls, tool calls, retries, changed files, and trace ID.
- R37. Eval checks verify 50+ tools remain available and that model-selected tools, subagents, typed patch planning, retries, validation, and final reports are visible in traces.
- R38. Eval failures include categories such as model output invalid, unsafe patch, patch did not apply, targeted tests failed, full tests failed, budget exhausted, and review rejected.
- R39. The final JSON report remains the main user-facing artifact for individual runs.

---

## Non-Goals

- NG1. No non-Python repo support in v2.
- NG2. No GitHub PR creation or hosted CI integration.
- NG3. No large arbitrary monorepo repair claim.
- NG4. No autonomous dependency installation or environment repair beyond the existing test command path.
- NG5. No claim of 100% deterministic live model success; v2 targets 90% live pass rate with traceable failures.

---

## Acceptance Examples

- AE1. **Multi-file success.** Given a fixture where a data contract drift affects parser and validator modules, when PatchPilot runs with OpenRouter and write/exec permissions, then it produces a source-only multi-file patch, passes targeted and full pytest, and reports all changed files.
- AE2. **Semantic validation.** Given a model patch that edits one relevant source file and one unrelated source file, when PatchPilot validates the plan, then it rejects or retries the plan because not every changed file serves the same root cause.
- AE3. **Retry success.** Given a first patch that applies but fails targeted pytest, when budgets remain, then PatchPilot records the failed attempt, gathers or repacks context, produces a revised patch, and eventually reports passing tests.
- AE4. **Hybrid patch consistency.** Given a patch plan whose structured edits and unified diff disagree, when PatchPilot validates it, then the plan is rejected before `fs.apply_patch`.
- AE5. **Artifact-aware context.** Given a long multi-file run, when context is compacted, then typed artifacts remain available exactly while bulky outputs are summarized.
- AE6. **Bounded review.** Given a passing patch, when the review subagent runs, then it checks correctness, necessity, and regression risk within its configured budgets and returns structured review output.
- AE7. **Suite proof.** Given the v2 live eval suite with 10+ fixtures, when it completes, then aggregate output reports at least 90% pass rate or clearly categorizes failures with trace IDs.

---

## Open Questions For Planning

- OQ1. Which OpenRouter model is the default v2 repair-power model at implementation time?
- OQ2. What exact fixture taxonomy should make up the first 10+ multi-file repos?
- OQ3. What budgets should apply per fixture for model calls, tool calls, retries, wall time, and cost?
- OQ4. How strict should review rejection be if tests pass but review flags missing validation?
- OQ5. How much provider-specific prompt caching behavior can be relied on without making the product less portable across OpenRouter routes?
