# composables

Reusable logic with no domain.

## Do

```ts
// useDebounce.ts — any feature could use this without knowing anything about its domain
export function useDebounce<T>(value: Ref<T>, delayMs: number) { ... }
```

## Don't

```ts
// ❌ this has domain — doesn't belong in src/composables/
export function useSimulationBudget(rule: BusinessRule) { ... }
```

A composable with a domain type (`BusinessRule`, `Simulation`, or any product entity) is born in `features/<feature>/composables/` and only moves up here by the rule of two: once a second feature needs the same logic. Don't create a generic composable here anticipating reuse.
