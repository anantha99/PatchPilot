# PatchPilot X-ARC Memo

## Built

PatchPilot now has a runnable Typer CLI, a coherent typed tool registry, guarded executor policy, six tool namespaces with 50+ concrete tools, OpenRouter-backed MiniMax M3 model profiles, structured model metadata, a parent repair runtime, typed diagnosis/review/patch-plan contracts, pytest and generic-command adapters, eleven v2 multi-file Python/pytest fixture repositories, JSONL traces, persisted final reports, and v2 fixture-suite aggregation.

V2 adds blind multi-file working-set inference, structured search/replace patch planning, clean local diff generation, semantic evidence-link checks, source-only write gates, typed repair attempts, retry scheduling after failed applied patches, bounded read-only diagnosis/review subagents, prompt-layer separation for cache-friendly provider calls, live-eval progress output, report paths, trace paths, usage/cost/cache summaries, and fixture metadata used only as a post-run oracle diagnostic. Product success is behavior-first; the hardened v2 fixture tests now force true multi-file repairs where the metadata claims them.

## Cut

Deep multi-language repair, hosted CI integration, PR creation, arbitrary dependency repair, and richer sandboxing are deferred. Offline tests use mocked OpenRouter transports so they stay cheap and repeatable; reviewer-facing product commands use OpenRouter/MiniMax against the v2 fixture suite.

## More Time

More time would go into stronger blind patch synthesis for arbitrary failures, deeper stack adapters, richer command sandboxing, CI-backed validation, live MiniMax M3 pass-rate tuning across the full v2 suite, and more public-repo recovery examples.

## Defended Decision

The runtime keeps product logic in PatchPilot-owned contracts instead of hiding it inside a graph framework. The important boundary is that fixture metadata stays in eval scoring, not in runtime prompts, configs, traces, or reports. Model selections, registry metadata, executor policy, semantic patch validation, retry attempts, subagent boundaries, traces, final reports, and eval checks are all inspectable Python objects and persisted artifacts.

## Inspect

Use `.\scripts\xarc-test.ps1 -Target test` for local verification. Use `patchpilot trace show <trace_id> --trace-dir <fixture>\.patchpilot\traces` to inspect JSONL traces, and open the matching `.patchpilot\reports\<trace_id>.json` for the final report. Use `patchpilot eval --suite v2 --repo fixtures\<fixture-name> --model-provider openrouter --model-profile v2-strong --live-eval` for one-fixture-at-a-time MiniMax proof runs; progress prints to stderr, JSON remains on stdout, and `<eval-root>\.patchpilot\reports\report.md` summarizes product pass rate plus multi-file contract match rate.
