# stores

Genuinely global state: shared across views or cached from the server. Nothing else lives here.

## Do

```ts
// features/<feature>/stores/example.ts — Pinia's "setup store" shape
export const useExampleStore = defineStore('example', () => {
  const items = ref<ExampleItem[]>([])
  async function fetchAll() { ... }
  return { items, fetchAll }
})
```

The id passed to `defineStore` is global in the app — prefix it with the feature name so two workstreams don't collide (`'example'`, `'simulation'`, never `'items'` or `'list'`).

## Don't

```ts
// ❌ local form/UI state doesn't become a store
export const useLoginFormStore = defineStore('loginForm', () => {
  const email = ref('')
  const showPassword = ref(false)
  return { email, showPassword }
})
```

That stays in a `ref` inside the view itself. A store per screen is an anti-pattern — if the state isn't shared across views or cached from the server, it isn't a store candidate.

## Contributing

A feature's store is born in `features/<feature>/stores/`. This root directory (`src/stores/`) is only for what **two or more features** legitimately share (e.g. the authenticated user's session) — promoted by the same rule of two that applies to components and types.
