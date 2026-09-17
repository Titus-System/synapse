---
name: testing
description: How tests are written in this project — the rule that a test asserts required behavior and never observed behavior, what to do when a test and the code disagree, how to prove a test can fail, and the layout, fixtures and commands the suite uses. Use whenever writing a test, changing an assertion, diagnosing a failing test, or reaching for xfail/skip/mock to turn a red suite green.
---

# Testing

One root rule: **a test states what the system must do, never what it happens to do.** Everything below follows from it.

## When a test and the code disagree

One of them is wrong. Decide which — in that order, test first — before changing either.

The question is never "how do I make this pass?" It is "which of these two is lying?" A test that fails because the code is broken has done its job; editing the assertion throws away the only signal that the bug exists, and ships it. A green suite is worth nothing on its own — it is only worth what its assertions claim.

If you cannot tell which is right, the behavior is undecided: ask, and do not encode a guess as an assertion. An assertion is a claim about what the system owes its callers, and once written, the next person will treat it as settled.

### Never accommodate wrong behavior

Each of these turns a red suite green while leaving the defect in place:

- Editing an expected value until it matches what the code printed.
- Widening an assertion — `in` where the contract says `==`, a subset where the contract names an exact set, a regex loose enough to match the bug.
- Asserting around the broken part instead of on it.
- `pytest.raises` wrapped around an exception the code should not be raising.
- `xfail` or `skip` used as a silencer.
- Regenerating a snapshot without reading the diff.
- Mocking the unit under test, so the defect can no longer reach the assertion.

Real case from this repo: `logger.exception()` was gluing the traceback onto `message` and never emitting the `exception` field, because `QueueHandler.prepare()` strips `exc_info`.

```python
# ❌ passes, and hides it — `in` is true even with a traceback glued to the message
assert "sandbox timed out" in payload["message"]
```

```python
# ✅ states the contract, fails until the code honors it
assert payload["message"] == "sandbox timed out"
assert "ValueError: boom" in payload["exception"]
```

The second one failed. The fix went into `app/core/logger.py`, not into the test.

`xfail` and `skip` are for a cause outside this codebase — an upstream bug, a service that is not reachable in CI — and the marker must name that cause. "Não passa" is not a cause.

```python
# ❌ a silencer
@pytest.mark.xfail(reason="quebrou depois do refactor")

# ✅ a fact about the environment, not about our code
@pytest.mark.skipif(not os.getenv("RABBITMQ_URL"), reason="precisa de um broker acessível")
```

## A test that cannot fail is not a test

Before trusting a new test, watch it fail for the right reason. Break the behavior it covers — revert the fix, invert a condition, delete the line it guards — run it, confirm it goes red with the message you expect, then restore. A test written against already-correct code and never seen red may be asserting nothing at all.

This is the whole workflow for a bug fix, in order:

1. Write the test that states the correct behavior.
2. Run it. It must fail, and the failure must describe the actual defect.
3. Fix the code.
4. Run it again.

## Test the path production uses

Pick the seam that includes the code that really runs. A unit test of `JsonFormatter` alone passes on an envelope that production never emits, because in production every record goes through `ContextQueueHandler.prepare()` first. `tests/app/core/test_logger.py` composes the two in the order `QueueListener` applies them — no threads, no files, no sockets, but the real sequence.

Mock what the test does not own: a broker, an outbound HTTP call, the clock. Never mock the thing under test.

## What earns a test

- **Cross-service contracts.** The log envelope is parsed by other services; a renamed top-level field breaks them silently. Assert the exact field set, not a subset.
- **Every rule written down in a skill or in `AGENTS.md`.** A rule nothing enforces is a suggestion.
- **Every bug fixed.** The regression test is the fix's receipt.
- **Branches that are hard to reach in production** — error paths, retries, fallbacks.

Not worth a test: that FastAPI routes, that Pydantic validates, that Prometheus counts. Test the code in `app/`, not its dependencies.

## Mechanics

The suite mirrors the package: `app/core/logger.py` is covered by `tests/app/core/test_logger.py`. End-to-end tests live in `tests/app/e2e/`, which `make test-e2e` runs on its own.

`asyncio_mode = "auto"`, so an async test is a plain `async def test_...` with no marker, and an async fixture needs no decorator of its own.

Fixtures in `tests/conftest.py`: `settings` (the resolved `Settings`), `api` (the FastAPI app), `client` (an `AsyncClient` on the ASGI app, no socket). The environment comes from `.env.test`, loaded before any `app` import.

Name a test as the sentence it proves — `test_correlation_fields_are_omitted_when_unset`, not `test_logger_2`. When it fails, that name is what the next person reads first.

One behavior per test. Separate arrange, act and assert with a blank line, and keep the assertions in a test about a single claim.

```python
def test_extra_is_namespaced_under_extra(envelope: Envelope) -> None:
    payload = envelope(extra={"exit_code": 0})

    assert payload["extra"] == {"exit_code": 0}
    assert "exit_code" not in payload
```

Run `make test` while working, `make pre-commit` before committing.

## Shared state

State that outlives a test will eventually decide whether another one passes, and the order dependency is found weeks later. Reset it in an autouse fixture — `tests/app/core/test_logger.py` does this for `job_id_ctx` and `user_id_ctx`.

Prometheus collectors are process-global and accumulate across a session: a test about a counter asserts the delta it caused, never an absolute value.

Nothing may depend on wall-clock time, network access, execution order, or a random seed that is not fixed.

## References

- The contract the log tests defend: `.agents/skills/observability/SKILL.md`
- Label and naming rules that deserve their own coverage: `.agents/skills/metrics/SKILL.md`
- Commit conventions for a fix and its regression test: `.agents/skills/commit-and-comments/SKILL.md`
- Lint, type-check and the full check: `AGENTS.md`, `Makefile`
