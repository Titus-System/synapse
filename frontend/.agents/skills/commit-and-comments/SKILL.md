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
- Explain the **when** — no comment should describe the current state of the project ("for now", "currently", "there are only 3 routes today", "until X is implemented"). If a comment's truth depends on today's date or today's file count, it's already lying to whoever reads it next.
- Restate in prose what the function/variable name already says. If a comment is needed to say what a well-named thing does, rename the thing instead of commenting it.

**The test before writing one:** if this file changes in a routine, unrelated way tomorrow, does the comment still hold? If the answer is "it depends," don't write it.

### Do

```ts
// ✅ explains a non-obvious constraint from an external system
// Vite replaces import.meta.env.VITE_X with text at build time — only works with literal access.
apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
```

```ts
// ✅ explains why an odd-looking guard exists
// 204 No Content has no body to deserialize.
if (response.status === 204) return undefined as T
```

### Don't

```ts
// ❌ narrates what the code already says on its own
// increment the counter by one
count.value++
```

```ts
// ❌ temporal — describes today's state, not a decision
// for now only the example feature exists
```

```ts
// ❌ a TODO with no owner or ticket is a comment that lies forever
// TODO: fix this later
```

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/), always in Brazilian Portuguese (pt-BR), one logical change per commit. `type` and `scope` stay in English (they're structural keywords, not prose); the summary and body are written in pt-BR. A stray fix noticed along the way — wrong-language variable, inconsistent indentation, an unrelated typo — doesn't belong in that commit, and usually doesn't belong in the current task at all; see "Stay in scope" in `AGENTS.md`.

```
<type>(<scope>): <summary in imperative mood>

- <topic — what changed and why, not extensive prose>
- <topic — one per bullet, only if there's more than one thing to say>

Review: <human|auto>
```

- **type**: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`, `perf`.
- **scope**: the feature or shared folder touched (`auth`, `simulation`, `http`, `config`) — omit when the change is repo-wide.
- **summary**: imperative, lowercase, no trailing period, under ~72 characters. `add`, never `added` or `adds`.
- **body (optional)**: short bullet points, not flowing paragraphs — each one a topic stating what changed and why. Skip it entirely when the summary line already says enough.
- **`Review` trailer (required)**: `human` if a developer actually read the diff and approved it before this commit was made; `auto` if nobody did — an autonomous agent run, a check-passed auto-merge, anything where no person looked at the change first. State what happened, not what looks better; the point is an honest signal future readers (and future audits) can trust.

No `Co-authored-by:` trailer, human or AI — `Review` already carries the signal that matters (whether a human looked at the diff); a second trailer naming who or what typed it adds nothing and doesn't belong in this project's history. This bans the trailer key, not the subject: this project is built on AI tooling, so naming a tool or model in the summary or a body bullet (`feat(rules): call GPT-4 for anomaly scoring`) is normal and expected — only a line starting with `Co-authored-by:` is off-limits.

The code checks are automatic — a Husky `pre-commit` hook runs `make pre-commit` (type-check + lint + test — see `AGENTS.md` and `Makefile`) before every commit. Everything above this line is convention, not hook-enforced: what matters most is that the code is correct; follow the message format by hand.

### Do

```
feat(auth): adiciona guarda de papel nas rotas protegidas

Review: human
```

```
fix(http): trata resposta 204 sem corpo

Review: auto
```

The body explains why, same rule as comments — topics, not the diff narrated in prose:

```
✅ fix(http): tenta novamente uma vez em timeout de rede

   - wifi instável na rede de demonstração causava falhas falsas durante simulações
   - uma única nova tentativa absorve isso sem mascarar erros reais

   Review: human
```

### Don't

```
❌ fixed stuff                                     — não diz o quê nem por quê
❌ WIP                                              — um commit não deveria existir nesse estado
❌ feat: add auth AND fix lint AND update deps      — três commits, não um
❌ Fix Http Error                                   — capitalizado como título; use imperativo minúsculo
❌ refactor(example): extract filter logic          — em inglês e sem o trailer Review
```

```
❌ fix(http): tenta novamente uma vez em timeout de rede

   Adicionado try/catch em volta do fetch e lógica de retry com contador.

   Review: human
```

(o corpo narra o diff em vez de explicar a decisão — o mesmo erro de um comentário de código que só repete o "como")

```
❌ fix(http): tenta novamente uma vez em timeout de rede

   Essa mudança foi necessária porque o wifi instável na rede de
   demonstração causava falhas falsas durante simulações, então depois
   de avaliar algumas opções uma única nova tentativa foi adicionada
   já que absorve essa falha sem mascarar erros reais que deveriam
   chegar ao chamador.

   Review: human
```

(explica a coisa certa — o porquê — mas como um parágrafo corrido; quebre em bullets curtos por tópico)

```
❌ Review: lol ninguém olhou isso, boa sorte
```

(o trailer é um marcador de status simples, não um lugar para comentário ou autodepreciação — `human`/`auto`, nada além disso)

```
❌ fix(http): tenta novamente uma vez em timeout de rede

   Review: auto
   Co-Authored-By: Claude <noreply@anthropic.com>
```

(sem trailer `Co-authored-by:` neste projeto — `Review: auto` já diz que um agente cuidou disso sem revisão humana)

```
✅ feat(rules): chama GPT-4 para pontuação de anomalias

   - GPT-4 sinaliza lançamentos de comissão que destoam do histórico do vendedor
   - mantido atrás de uma feature flag até medir a taxa de falsos positivos

   Review: human
```

(citar uma ferramenta ou modelo é normal em qualquer parte da mensagem — o que é proibido é o trailer `Co-authored-by:`, não o assunto da mudança)

## References

- General structure conventions and "hot files" (change in its own PR): `AGENTS.md`
- Check that has to pass before committing: `make pre-commit`, enforced by the `.husky/pre-commit` hook
- The do/don't style used throughout this project: `src/config/README.md`, `src/services/README.md`, `src/features/README.md`
