# services

`http.ts` is the only place in the project allowed to call `fetch`.

## How it works

Every API call goes through `http`, so baseURL, headers, error handling, and (in the future) authentication exist in one place:

```ts
export const http = {
  get: <T>(path, signal?) => ...,
  post: <T>(path, body?, signal?) => ...,
  put: ...,
  patch: ...,
  delete: ...,
}
```

A non-2xx response becomes an `HttpError`, with `status` and the body (`ApiError`, from `@/types/api`) already deserialized.

## Do

In `features/<feature>/services/<feature>.api.ts`:

```ts
import { http } from '@/services/http'

export function listExamples(signal?: AbortSignal) {
  return http.get<Paginated<ExampleItem>>('/examples', signal)
}
```

Catch `HttpError` in the store or the view, where the error is handled and shown to the user.

## Don't

```ts
// ❌ no feature calls fetch directly
const response = await fetch('/api/examples')
```

```ts
// ❌ the service layer doesn't handle errors or hold state — it only builds the call
export async function listExamples() {
  try {
    return await http.get('/examples')
  } catch {
    return []
  }
}
```

**Hot file**: a change in `http.ts` affects all three workstreams at once. Its own small PR, flagged to the team, never bundled with a feature.
