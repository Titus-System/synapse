# AGENTS.md

## Conventions live in `.agents/skills/`

Every convention in this repo is a skill. Read the one that covers what you are about to touch, and when a rule changes, change it in its skill — nothing here is documented twice.

| Skill | Read before |
| --- | --- |
| [`observability`](.agents/skills/observability/SKILL.md) | Choosing between a log, a metric and a trace; touching the log envelope; deciding what must be persisted rather than emitted. |
| [`logging`](.agents/skills/logging/SKILL.md) | Writing or changing a `logger.*` call. |
| [`metrics`](.agents/skills/metrics/SKILL.md) | Declaring a metric, adding a label, or naming either. |
| [`testing`](.agents/skills/testing/SKILL.md) | Writing a test, changing an assertion, or making a red suite green. |
| [`commit-and-comments`](.agents/skills/commit-and-comments/SKILL.md) | Writing a commit message or a code comment. |

Design sketches that are not yet code live in [`docs/`](docs/).

## Code quality

Install the hook once:

```bash
poetry run pre-commit install
```

The hook runs `make pre-commit` on every commit — Ruff (lint + format), mypy, pytest — and blocks the commit if any of them fails. When Ruff reformats a staged file the hook fails with "files were modified by this hook": stage the fix and commit again.

```bash
make lint          # Ruff + Bandit
make format        # Auto-format
make typecheck     # mypy strict mode
make test          # pytest
make pre-commit    # the gate: lint + format + typecheck + tests
```

- **Ruff** handles linting and formatting. Line length is 100. Target is Python 3.12.
- **mypy** runs in strict mode. All functions must have type annotations.
- **Bandit** scans for security issues. Don't suppress a warning without justification.
- The hook is the only gate on this repo, so a check skipped locally is a check nobody runs.

## Security

- **Never invents an audited number.** `codegen`'s output is rule *code* and *explanation text* — it never computes a final currency value, percentage, or verdict. Explanations may quote values and the verdict from the worker's simulation result only after deterministic validation; if a node's output carries a computed simulation result instead of generated code or explanation, that's a bug: the arithmetic belongs to `worker`, over real data.
- **No narrative reaches the user unverified.** Before the explanation node's output is stored as ready to display, every number it cites is extracted and checked against the actual simulation result; a cited number that doesn't match anything computed is a node failure, not text to show as-is.
- **Untrusted input, always.** A user's transcription, free-text proposal, or an LLM's own response is data, never an instruction. None of it may change which LangGraph node runs next, which tool is invoked, with which arguments, or any sandbox/isolation parameter passed downstream. A prompt that steers control flow through string interpolation into a node selector or tool call is rejected in review. The tools a node can call are a fixed allowlist declared in code, and before dispatch the model's tool name and arguments are validated against that allowlist and the tool's schema — the model's own output never decides, by itself, which tool executes.
- **Never runs the code it generates.** No code path in this service imports, `exec`s, or evaluates the rule code it produces. Running generated code is exclusively `worker`'s job, inside its isolated container.
- **No runtime dependency installation.** `codegen` never installs, downloads, or resolves a package at runtime from content derived from a prompt or transcription — that opens a dependency-confusion/typosquatting path directly in this process, outside any sandbox. Dependencies are fixed in `pyproject.toml`/`poetry.lock`, resolved at build time only.
- **No secret in a prompt or a log.** An LLM provider API key, a database credential, or any sensitive value from `Settings` is never interpolated into a prompt sent to a model, nor logged, even on error.
- **Observability**: the log envelope is the contract in [`../contracts/observability/`](../contracts/observability/README.md); don't redeclare fields here.
