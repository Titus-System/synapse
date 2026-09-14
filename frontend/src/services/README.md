# services

`http.ts` is the only place in the project allowed to call `fetch`.

## How it works

Every REST call goes through `http`, so base URL, headers and error handling stay in one place. Authentication is intentionally absent in Sprint 1.

```ts
export const http = {
  get: <TResponse>(path, signal?) => ...,
  post: <TResponse, TBody>(path, body?, signal?) => ...,
  url: (path) => ...,
}
```

A non-2xx response becomes an `HttpError`. Validation errors expose `fieldErrors` with a readable field name and message. Server and connection failures use user-facing messages and never expose a raw HTTP status as display text.

`api.ts` maps the operations from `contracts/http/openapi.yaml` to typed calls. The `acompanharJob` entry only returns the typed stream URL; opening and consuming the SSE connection belongs to T-072.

## Do

Use `apiClient` for the operations already described by the OpenAPI contract. If a feature later needs a feature-specific endpoint that is not part of the shared client, keep the call in `features/<feature>/services/` and build it with `http`.

Catch `HttpError` in the store or the view, where the error is handled and shown to the user.

## Don't

```ts
// ❌ no feature calls fetch directly
const response = await fetch('/api/examples')
```

```ts
// ❌ the service layer doesn't hold UI state
export async function carregar() {
  try {
    return await apiClient.listarJobs()
  } catch {
    return []
  }
}
```

**Hot file**: a change in `http.ts` affects all workstreams at once. Its own small PR, flagged to the team, never bundled with a feature.
