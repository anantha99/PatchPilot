# Assignment Brief

The assignment is to build a production-shaped autonomous agent, from scratch, in a domain of your choosing. The brief is scoped beyond five days. We evaluate depth, not completion.

Five properties have to hold across the build. Every other dimension (language, framework, interface, execution model, context strategy, evaluation harness) is left to you.

1. 50+ tools across 4+ namespaces. Tool selection is driven by the model rather than routed by hand, and the registry has to remain coherent at fifty tools rather than collapsing into a chain of fifty conditional dispatches.

2. Subagent orchestration. At least one tool spawns a subagent that executes in an isolated context, holds its own scoped tool set, and returns a structured result to the parent. A function call relabelled as a subagent does not satisfy the requirement.

3. Long-horizon execution. The agent completes a task spanning at least 20 tool calls within a single session without loss of plan coherence, and the context-management strategy is expressed in the code itself rather than left implicit.

4. Production scaffolding. The build includes observability, retries with exponential backoff, rate limiting on external calls, typed error handling, an evaluation harness, and a test suite covering both unit and integration paths. The codebase is structured for deployment rather than for a notebook.

5. Composable tool inputs and outputs. At least one tool consumes the structured output of another, so that tools compose into chains rather than terminate at single calls.

Domains that fit the brief include repository automation, deep research, a devops or SRE agent, a personal-operations agent, and a coding agent. Pick whatever admits depth within five days of focused work.

A one-page MEMO.md is placed at the repository root, documenting what you built, what you cut, what additional time would have addressed, and one design decision you would defend against an alternative an engineer might reasonably have made.

Submission, by reply to this thread:

- A public GitHub repository. We read both the code and the commit history.
- A three-to-five-minute video walkthrough that demonstrates the working build, walks us through the most substantive part of the code, and surfaces one moment where you and the model diverged.
- Your prompts and full session traces in the native export format of the tool you used. For Claude Code, the session JSONL files at `~/.claude/projects/<project>/` are accepted; for Codex, the equivalent session export.
- The MEMO.md (kept in the repository alongside the code is fine).

Terms:

- Five focused days from today. Reply on this thread within five days of this email.
- The strongest submissions are invited to a thirty-minute review call, after which an offer may follow.

Anas
