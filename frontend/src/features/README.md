# Features

Each folder here is a closed domain: everything that workstream needs lives inside it. This is what lets three people work on the project at the same time without conflicting, and what lets you ask an AI agent to "implement X in `src/features/x/`" with the whole context fitting inside one directory.

## Internal shape (always the same)

```
features/<name>/
├── routes.ts            # required — exports RouteRecordRaw[]
├── types.ts             # types only this feature uses
├── views/               # routable screens
├── components/          # components for this feature only (+ *.spec.ts next to them)
├── composables/         # reusable view logic
├── stores/              # state shared across this feature's views
└── services/            # this feature's API calls
```

Only `routes.ts` is required. Create the other folders as needed — a small feature can have just `routes.ts` and `views/`.

`src/features/example/` is the complete template. Copy its structure when creating a real feature.

## Convention by file type

**`routes.ts`** exports `RouteRecordRaw[]`. `meta.navLabel` makes the route show up in the sidebar (`TheSidebar`) on its own — without that field, the route exists but doesn't appear in the menu.

```ts
export default [
  {
    path: '/example',
    component: () => import('./views/ExampleListView.vue'),
    meta: { navLabel: 'Example', navOrder: 10 },
  },
] satisfies RouteRecordRaw[]
```

**`views/`** — routable screen. Fetches data, orchestrates components, knows the router. Rule of thumb to tell it apart from a component: a view doesn't receive props.

```vue
<!-- ✅ a view fetches its own data -->
<script setup lang="ts">
const store = useExampleStore()
onMounted(() => store.fetchAll())
</script>
```

```vue
<!-- ❌ a view doesn't receive props — if it looks like this, it's a component, not a view -->
<script setup lang="ts">
defineProps<{ items: ExampleItem[] }>()
</script>
```

**`components/`** — knows the feature's domain, but doesn't fetch data or read a store. Receives by prop, notifies by event. If it needs the route or the API, it's probably a view. Tests live next to it, as `*.spec.ts` — not in a central `__tests__` folder, where tests grow stale without anyone noticing.

**`composables/`** — reusable view logic, no global state and no direct network access. This is where what would bloat the view migrates to: the project's target is views under ~200 lines.

**`stores/`** — Pinia's "setup store" shape. Use only for what's shared across the feature's views or cached from the server; form/UI-local state stays in a `ref` in the view. The id passed to `defineStore` is global in the app — prefix it with the feature name so two workstreams don't collide.

**`services/`** — builds the HTTP call via `http` from `@/services/http` and returns the type, nothing else. No state, no error handling — that lives in the store or the view that consumes it.

**`types.ts`** — types only this feature uses. The rule of two (below) decides when a type moves up to `src/types/`.

## Rules

**1. A feature never imports from another feature.** ESLint blocks it (rule `app/feature-boundaries`). If you needed to, the code is shared: promote it to `src/`.

**2. Rule of two — promote only on the second use.** A component, type, or helper only leaves a feature for `src/` once a second feature needs it. Duplicating once is cheaper than abstracting too early and getting it wrong.

**3. Inside a feature, relative imports. Outside, `@/`.** This makes rule 1 self-enforcing: if you wrote `@/features/...`, it's wrong by definition.

**4. Nobody edits `src/router/index.ts`.** Declare the route in your feature's `routes.ts` — the router aggregates by glob. To show up in the sidebar, just add `meta: { navLabel: 'Name', navOrder: 20 }`.

**5. Hot files go in their own PR.** These are `src/types/api.ts`, `src/services/http.ts`, `src/components/Base*`, and `src/layouts/*` — the only points where the three workstreams intersect. Change them in a small PR, flag it to the team, never alongside a feature.

## Ownership

| Feature   | Owner | Status                            |
| --------- | ----- | --------------------------------- |
| `example` | —     | reference template, to be deleted |

Fill this in as real features get created. One owner per feature: a PR that only touches `features/<yours>/**` merges without contention.
