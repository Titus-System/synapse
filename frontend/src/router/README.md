# router

`index.ts` sets up the router — and is the file nobody edits to add a screen.

## How it works

```ts
const modules = import.meta.glob('../features/*/routes.ts', { eager: true })
```

Each feature declares its routes in `features/<feature>/routes.ts`; this file only aggregates all of them via glob, resolved at build time by Vite. `eager: true` keeps the route list synchronous — the views' components still load on demand through the `import()` inside each route, so this doesn't affect code-splitting.

Route order is deterministic (Vite returns the glob keys sorted by path), and the catch-all (404) stays explicit and last in the array — the glob doesn't guarantee a feature route won't come after it.

## Do

To add a screen, create or edit `features/<feature>/routes.ts`:

```ts
export default [
  { path: '/example', component: () => import('./views/ExampleListView.vue') },
] satisfies RouteRecordRaw[]
```

## Don't

```ts
// ❌ never list a feature's routes directly in src/router/index.ts
routes: [{ path: '/example', component: ExampleListView }]
```

If you felt the need to edit `index.ts` to add a screen, stop — the route belongs in your feature's `routes.ts`. A structural change to the aggregator itself (changing the glob pattern, say) affects all three workstreams at once and deserves its own PR, flagged to the team.
