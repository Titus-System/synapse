# services

`http.ts` is the only place in the project allowed to call `fetch`.

## How it works

REST and SSE requests go through `http`, which obtains the current Keycloak token after awaiting `updateToken(30)` and sends it in the `Authorization` header. Tokens remain in memory. A temporary refresh failure stops the request without clearing the session; a 401 response starts login again.

```ts
export const http = {
  get: <TResponse>(path, signal?) => ...,
  post: <TResponse, TBody>(path, body?, signal?) => ...,
  stream: (url, signal) => ...,
  url: (path) => ...,
}
```

A non-2xx response becomes an `HttpError`. Validation errors expose `fieldErrors` with a readable field name and message. Server and connection failures use user-facing messages and never expose a raw HTTP status as display text.

`api.ts` maps the operations from `contracts/http/openapi.yaml` to typed calls. The `acompanharJob` entry returns the stream URL. `jobEvents.ts` opens it through `http.stream`, consumes the SSE frames and manages reconnection, cancellation and result deduplication. Each reconnection obtains a current token.

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
