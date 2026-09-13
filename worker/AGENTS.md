# AGENTS.md

## Security

- **Generated rule code only runs inside the sandbox container.** No code path in `worker` imports, `exec`s, or evaluates a generated rule outside the ephemeral container created for the job. Calling the rule's code directly in the worker process — even for a "quick check" — is rejected in review.
- **Isolation flags are never relaxed for convenience.** The container is created with its isolation already configured (no privileged mode, no host network, no writable mount beyond the job's own workspace, resource limits applied). A change that removes, weakens, or makes conditional any of these flags — even temporarily, even for local debugging — needs an explicit architectural decision, not a one-line fix.
- **The verdict is computed outside the container.** `worker`'s own process, never the sandboxed code, decides pass/fail against baseline and budget, from the container's raw output data. The sandboxed process returns data; it never returns a verdict, and `worker` never trusts a verdict field coming back from inside the container.
- **A hung job is terminated, not left running.** Every sandbox execution has a maximum wall-clock time; `worker` terminates the container when it's exceeded instead of waiting indefinitely — an unbounded wait is a denial-of-service surface.
- **A container is never reused across jobs.** Each job gets its own container, discarded once the job finishes; nothing from one job's filesystem or process state is available to the next job, even for the same tenant.
- **Observability**: the log envelope is the contract in [`../contracts/observability/`](../contracts/observability/README.md); don't redeclare fields here.

## Verify

```bash
make pre-commit   # ruff (lint + format) + mypy + pytest — the gate for this component
```
