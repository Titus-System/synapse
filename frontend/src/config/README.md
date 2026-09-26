# config

`env.ts` is the only place in the project allowed to read `import.meta.env`. Everything else imports `config` from here.

## How it works

```
.env                    →  actual value (not versioned; see .env.example at the root)
env.d.ts                →  the variable's type (autocomplete + type-check)
src/config/env.ts        →  reads and distributes — the ONLY point of reading
rest of the app          →  import { config } from '@/config/env'
```

The `app/env-single-entry` ESLint rule blocks any `import.meta.env` outside this file — including inside a `.vue`'s `<script setup>`.

## Do

```ts
import { config } from '@/config/env'

fetch(`${config.apiBaseUrl}/examples`)
```

```ts
// inside env.ts — access is always literal
apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
```

## Don't

```ts
// ❌ in any file outside src/config/env.ts
const url = import.meta.env.VITE_API_BASE_URL
```

```ts
// ❌ even inside env.ts — dynamic access isn't substituted at build time
const key = 'VITE_API_BASE_URL'
const url = import.meta.env[key] // undefined in production
```

Vite replaces `import.meta.env.VITE_X` with text at build time; that only works with literal access. Dynamic access works in dev and returns `undefined` in the production build.

Never put a secret in a `VITE_*` variable — anything with that prefix is embedded in the bundle as plain text and visible in anyone's DevTools. API keys and tokens live in the backend.

## Adding a new variable

1. Declare the type in `env.d.ts` at the project root (`VITE_` prefix required).
2. Document it in `.env.example`, at the root, with its default value.
3. Read it here, in `env.ts`, and expose it in `config`.
