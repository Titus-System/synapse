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
