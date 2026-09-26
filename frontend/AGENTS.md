# Frontend — instructions for agents

Vue 3.5 (`<script setup lang="ts">`) + Vite 8 + TypeScript 6 + Pinia 4 + vue-router 5 + Tailwind 4. Node 24.

## Before calling it done

Run it and fix what comes up. Code that hasn't been through this isn't done:

```sh
make check   # type-check + lint + test, in that order — see Makefile
```

A Husky `pre-commit` hook runs the same check automatically before every commit — it installs itself on `npm install`. Running `make check` yourself before staging just means you find out sooner. Commit message conventions live in `.agents/skills/commit-and-comments/SKILL.md`; that one isn't hook-enforced, follow it by hand.

## Stay in scope

Touch only what the task asked for. A variable in the wrong language, inconsistent indentation, an outdated comment, an unrelated typo, a file that could be split up — if it's pre-existing and not what you were asked to do, leave it alone, even when it's real debt. It may be mid-migration, or intentional for a reason the current task doesn't have context on; either way, it's a separate decision made in a separate cycle, and folding it into an unrelated diff makes that diff harder to review and silently overrides a decision that wasn't yours to make right now.

This doesn't cover automated, tool-driven formatting already wired into the project (`make lint`, prettier) — that's a single consistent pass applied uniformly, not a manual judgment call, and always fine to run.

Notice something out of scope worth fixing? Say so and let the person ask for it — don't just do it. If asked to do something broad (e.g. "translate the whole project"), that request is itself the scope, and a sweeping change is exactly what was asked for.

## Structure

Feature-first. Each domain is a closed folder in `src/features/<name>/` with a fixed internal shape (`routes.ts`, `types.ts`, `views/`, `components/`, `composables/`, `stores/`, `services/`). The full convention and boundary rules are in `src/features/README.md` — read it before creating a new file.

What's shared lives at the root of `src/`:

| Folder         | What goes there                                                          |
| -------------- | ------------------------------------------------------------------------ |
| `components/`  | domain-free primitives: `Base*` (reusable), `The*` (unique on screen)    |
| `composables/` | generic logic, no domain                                                 |
| `config/`      | `env.ts` — the only place that reads `import.meta.env`                   |
| `services/`    | `http.ts` — the only place that calls `fetch`                            |
| `stores/`      | only genuinely global state                                              |
| `types/`       | `api.ts` (envelopes and errors) and `router.d.ts` (`meta` fields)        |
| `layouts/`     | layouts + `registry.ts`, which defines the valid values of `meta.layout` |
| `views/`       | views with no feature owner (404)                                        |
| `router/`      | `index.ts` aggregates the features' `routes.ts` via glob                 |

## Where new things go

- New view → `features/<feature>/views/XView.vue` + entry in the feature's `routes.ts`. Never edit `src/router/index.ts`.
- New component → `features/<feature>/components/`. Only moves to `src/components/` once a **second** feature needs it.
- API call → `features/<feature>/services/<feature>.api.ts`, using `http` from `@/services/http`.
- New type → `features/<feature>/types.ts`. Moves up to `src/types/` only when a second feature uses it.
- New environment variable → declare the type in `env.d.ts`, document it in `.env.example`, and read it in `src/config/env.ts`. The rest of the code imports `config` from `@/config/env` and never reads `import.meta.env`.

## Rules the lint enforces

A feature never imports from another feature, and shared code never imports from a feature. If you needed to, promote the code instead of working around the rule. Inside a feature use relative imports (`../types`); for shared code use `@/`.

`import.meta.env` may only appear in `src/config/env.ts`. Access has to be literal (`import.meta.env.VITE_X`): Vite replaces it with text at build time, so dynamic access works in dev and returns `undefined` in production. No secrets in `VITE_*` variables — anything with that prefix ships to the bundle as plain text.

## TypeScript

On top of `strict`, the tsconfigs turn on `noImplicitReturns`, `noFallthroughCasesInSwitch`, `noImplicitOverride`, `allowUnusedLabels: false`, and (only in `tsconfig.app.json`) `noUncheckedIndexedAccess`.

Two flags were evaluated and dropped due to real friction against this project's code, not laziness — don't re-enable them without reopening the discussion:

- `noPropertyAccessFromIndexSignature` — would require `route.params['id']` instead of `route.params.id` in every view that reads a route param, which is constant usage.
- `exactOptionalPropertyTypes` — conflicts with library types that use `| undefined` instead of `?:` (e.g. DOM's `RequestInit.body`, used in `services/http.ts`); tends to recur with every new integration against DOM/vue-router/Pinia.

## Conventions

- Component name is always multi-word PascalCase. Views end in `View.vue`.
- Before creating a component or helper, search `src/components/`, `src/composables/`, and the feature itself. Duplication is the most common mistake here.
- Styling is Tailwind in the template. No custom CSS: no `<style scoped>`. A new theme token goes in `@theme` in `src/assets/main.css`. Tailwind classes are always literal and complete — an interpolated string (`` `bg-${color}-500` ``) isn't picked up by the scanner.
- Tests live next to the file they test, as `*.spec.ts`.
- A view fetches data and knows the router; a component receives props and emits events. If a component needs the route or API data, it's probably a view. Rule of thumb: a view doesn't receive props.
- A store is for state shared across views or cached from the server. Local form/UI state stays in a `ref` inside the view — a store per screen is an anti-pattern.
- A large file is expensive to review and expensive for an agent. Target: views under ~200 lines; anything beyond that goes into a composable.
- No generic `utils.ts`. A file is named after its subject.
- No barrel `index.ts` per folder. The one deliberate exception is `src/layouts/registry.ts`.

## Hot files

`src/types/api.ts`, `src/services/http.ts`, `src/components/Base*`, `src/layouts/*`. These are where the three workstreams intersect. Changes to them go in their own small PR, never bundled with a feature.

## Commits and comments

The commit message convention (Conventional Commits, in Brazilian Portuguese) and the code comment convention (only the "why", never a temporal comment) live in `.agents/skills/commit-and-comments/SKILL.md`.

## Security

- **No calculated display value.** A component, view, composable or store never derives a number the user relies on financially — no arithmetic on monetary/percentage fields (`valor * ...`, `total - desconto`, rounding a rate), no client-side viability/approval verdict, no diff against baseline computed in TS. Every such value arrives already computed from the `api` response and is only formatted (currency/date/locale) or styled, never derived. A PR that adds a formula over raw numeric fields to a component/view/store — even a "simple" one — is rejected; the calculation belongs to a backend service.
- **No business rule branches on domain data.** A `v-if` or `computed` may branch on UI state (loading, selected tab, form validity) but never on a business threshold (e.g. whether a rule is within budget) — that verdict is a field the api already computed, not something re-derived from raw numbers in the frontend.
- **Auth token never touches persistent storage.** The Keycloak access/refresh token is never written to `localStorage`, `sessionStorage`, or a JavaScript-readable cookie — an XSS that finds it there can exfiltrate it. The OIDC adapter keeps it in memory only; a reload restores the session through a silent SSO check against Keycloak's own session, never by reading something the app persisted itself.
- **No unsanitized HTML injection.** `v-html` is never used to render text that originated from a user proposal, a transcription, or an AI-generated explanation. Vue's default template escaping is what protects against XSS; bypassing it needs an explicit, reviewed sanitizer, not a default choice.
- **No raw error rendered to the user.** An api error response's internal detail (stack trace, exception message, internal field name) is never interpolated directly into a view or toast; the frontend maps a known error code to a user-facing message.
- **Observability**: the log envelope is the contract in [`../contracts/observability/`](../contracts/observability/README.md); don't redeclare fields here.
