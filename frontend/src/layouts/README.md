# layouts

The shells that wrap views — e.g. one layout with a sidebar, another full-screen with no navigation for screens like login.

## How it works

`registry.ts` maps name → component and is the project's one deliberate barrel file — it exists to give the layout a stable name and derive the `LayoutName` type (used in `src/types/router.d.ts`) from a single place.

`App.vue` reads `route.meta.layout`, resolves it against the registry, and renders:

```
feature's routes.ts → meta: { layout: 'blank' }
        ↓
App.vue → layouts[route.meta.layout ?? 'default']
```

A route with no `meta.layout` declared falls back to `default`.

## Do

In `features/<feature>/routes.ts`:

```ts
{ path: '/login', component: () => import('./views/LoginView.vue'), meta: { layout: 'blank' } }
```

New layout: create the `.vue` here and register it in `registry.ts`. That already makes the name available for any feature to use in `meta.layout`, with autocomplete and type checking.

## Don't

Don't edit a feature to switch its layout via an `if`/conditional in the view — the choice is declarative, via `meta.layout` on the route. Don't create a second registry file — `registry.ts` is the only place that maps name to component.
