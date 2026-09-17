---
name: commit-and-comments
description: This project's conventions for git commit messages and code comments. Use whenever writing or reviewing a commit message, drafting a PR description, adding a code comment, reviewing an existing one, or deciding whether a comment should be removed for describing a temporary state instead of a decision.
---

# Commit & Comments

Two conventions, one root rule in common: explain a **decision**, never narrate a **state**.

## Code comments

A comment exists only to explain a decision that isn't obvious from the code — never the mechanics of what the code does, and never anything that describes a moment in time.

**What a comment must never do:**

- Explain the **how** — the code already shows that; repeating it in prose is noise that goes stale the moment the code changes.
- Explain the **when** — no comment should describe the current state of the project ("for now", "currently", "there's only one agent today", "until the consumer is wired up"). If a comment's truth depends on today's date or today's file count, it's already lying to whoever reads it next.
- Restate in prose what the function/variable name already says. If a comment is needed to say what a well-named thing does, rename the thing instead of commenting it.

**The test before writing one:** if this file changes in a routine, unrelated way tomorrow, does the comment still hold? If the answer is "it depends," don't write it.

### Do

```python
# ✅ explains a non-obvious constraint from an external system
# The QueueListener formats records in another thread, where the ContextVars of
# the task that logged them are no longer visible — copy them onto the record.
record.job_id = job_id_ctx.get()
```

```python
# ✅ explains why an odd-looking guard exists
# A span context is invalid outside an instrumented flow; the log line is still
# valid without the ids.
if not span_context.is_valid:
    return None
```

### Don't

```python
# ❌ narrates what the code already says on its own
# increment the job counter by one
job_runs.labels(job_name="generate_code").inc()
```

```python
# ❌ temporal — describes today's state, not a decision
# for now the only agent is the planner
```

```python
# ❌ a TODO with no owner or ticket is a comment that lies forever
# TODO: fix this later
```

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), always in Brazilian Portuguese (pt-BR), one logical change per commit. `type` and `scope` stay in English (they're structural keywords, not prose); the summary and body are written in pt-BR. A stray fix noticed along the way — wrong-language variable, a lint rule tightened in passing, an unrelated typo — doesn't belong in that commit, and usually doesn't belong in the current task at all.

```
<type>(<scope>): <summary in imperative mood>

- <topic — what changed and why, not extensive prose>
- <topic — one per bullet, only if there's more than one thing to say>

Review: <human|auto>
```

- **type**: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`, `perf`.
- **scope**: the module or package touched (`logger`, `metrics`, `config`, `worker`, `db`) — omit when the change is repo-wide.
- **summary**: imperative, lowercase, no trailing period, under ~72 characters. `adiciona`, never `adicionado` or `adicionando`.
- **body (optional)**: short bullet points, not flowing paragraphs — each one a topic stating what changed and why. Skip it entirely when the summary line already says enough.
- **`Review` trailer (required)**: `human` if a developer actually read the diff and approved it before this commit was made; `auto` if nobody did — an autonomous agent run, a check-passed auto-merge, anything where no person looked at the change first. State what happened, not what looks better; the point is an honest signal future readers (and future audits) can trust.

No `Co-authored-by:` trailer, human or AI — `Review` already carries the signal that matters (whether a human looked at the diff); a second trailer naming who or what typed it adds nothing and doesn't belong in this project's history. This bans the trailer key, not the subject: this project is built on AI tooling, so naming a tool or model in the summary or a body bullet (`feat(agents): usa Claude para planejar a execução`) is normal and expected — only a line starting with `Co-authored-by:` is off-limits.

The code checks are automatic — the `pre-commit` hooks (installed once with `poetry run pre-commit install`) run Ruff, mypy and Bandit before every commit, and `make pre-commit` runs lint + format + type-check + tests in one go; see `AGENTS.md` and the `Makefile`. Everything above this line is convention, not hook-enforced: what matters most is that the code is correct; follow the message format by hand.

### Do

```
feat(logger): adiciona job_id ao contexto de correlação

Review: human
```

```
fix(metrics): evita registrar o mesmo coletor duas vezes

Review: auto
```

The body explains why, same rule as comments — topics, not the diff narrated in prose:

```
✅ fix(worker): tenta novamente uma vez em timeout do RabbitMQ

   - a rede do laboratório derruba a conexão AMQP por alguns segundos e gerava falhas falsas
   - uma única nova tentativa absorve isso sem mascarar erros reais

   Review: human
```

### Don't

```
❌ fixed stuff                                     — não diz o quê nem por quê
❌ WIP                                              — um commit não deveria existir nesse estado
❌ feat: add auth AND fix lint AND update deps      — três commits, não um
❌ Fix Logger Error                                 — capitalizado como título; use imperativo minúsculo
❌ refactor(metrics): extract label validation      — em inglês e sem o trailer Review
```

```
❌ fix(worker): tenta novamente uma vez em timeout do RabbitMQ

   Adicionado try/except em volta do connect e lógica de retry com contador.

   Review: human
```

(o corpo narra o diff em vez de explicar a decisão — o mesmo erro de um comentário de código que só repete o "como")

```
❌ fix(worker): tenta novamente uma vez em timeout do RabbitMQ

   Essa mudança foi necessária porque a rede instável do laboratório
   derrubava a conexão AMQP por alguns segundos, então depois de avaliar
   algumas opções uma única nova tentativa foi adicionada já que absorve
   essa falha sem mascarar erros reais que deveriam chegar ao chamador.

   Review: human
```

(explica a coisa certa — o porquê — mas como um parágrafo corrido; quebre em bullets curtos por tópico)

```
❌ Review: lol ninguém olhou isso, boa sorte
```

(o trailer é um marcador de status simples, não um lugar para comentário ou autodepreciação — `human`/`auto`, nada além disso)

```
❌ fix(worker): tenta novamente uma vez em timeout do RabbitMQ

   Review: auto
   Co-Authored-By: Claude <noreply@anthropic.com>
```

(sem trailer `Co-authored-by:` neste projeto — `Review: auto` já diz que um agente cuidou disso sem revisão humana)

```
✅ feat(agents): chama Claude para pontuar anomalias na execução

   - o modelo sinaliza execuções que destoam do histórico do job
   - mantido atrás de uma flag de configuração até medir a taxa de falsos positivos

   Review: human
```

(citar uma ferramenta ou modelo é normal em qualquer parte da mensagem — o que é proibido é o trailer `Co-authored-by:`, não o assunto da mudança)

## References

- Code quality rules (Ruff, mypy strict, Bandit) and the manual checks: `AGENTS.md`
- Check that has to pass before committing: `make pre-commit`, plus the `pre-commit` hooks installed by `poetry run pre-commit install`
- Cross-service contracts a commit must not break on its own (the log envelope) and the do/don't style used throughout this project: `CONTRIBUTING.md`
