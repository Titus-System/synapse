# types

Two files, two different roles.

## `api.ts`

Transport types shared by every feature: the pagination envelope (`Paginated<T>`), the error shape (`ApiError`).

```ts
// ✅ belongs in api.ts — transport infrastructure, not domain
export interface Paginated<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}
```

```ts
// ❌ doesn't belong in api.ts — this is a domain type, born in the feature's types.ts
export interface BusinessRule {
  id: string
  statement: string
}
```

**Hot file**: all three workstreams depend on it. Changes go in their own small PR, flagged to the team, never bundled with a feature.

## `router.d.ts`

Extends vue-router's `RouteMeta` with the fields the project uses in `meta` (`layout`, `navLabel`, `navOrder`). It's a `declare module`, generates no code — just types, and gives autocomplete in each feature's `routes.ts`.

```ts
// new field in meta: declare here, with the behavior when absent
interface RouteMeta {
  requiresAuth?: boolean // absent = public route
}
```

## Contributing

Rule of two: a type only moves up from a feature to here once a **second** feature needs it. See `src/features/README.md`.
