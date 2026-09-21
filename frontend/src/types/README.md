# types

Two files, two different roles.

## `api.ts`

Types shared by the REST transport live here. They mirror the shapes used by `contracts/http/openapi.yaml` and the domain schemas referenced by it: request bodies, jobs, simulation results and the standard API error body.

The types are written by hand. They are transport declarations only; they do not calculate values or reproduce backend business rules.

When a contract field is optional, the TypeScript field is optional as well. Existing contract examples are deserialized in `api.contract.spec.ts` so changes that stop matching the shared examples fail in the frontend gate.

**Hot file**: all workstreams can depend on it. Changes go in their own small PR, flagged to the team, never bundled with a feature.

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
