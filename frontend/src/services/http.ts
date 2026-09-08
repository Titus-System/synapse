import { config } from '@/config/env'
import type { ApiError } from '@/types/api'

/** Non-2xx response error. Carries the status and the body returned by the API. */
export class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: ApiError | null,
  ) {
    super(body?.message ?? `HTTP ${status}`)
    this.name = 'HttpError'
  }
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

async function request<T>(
  method: Method,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const isFormData = body instanceof FormData
  const headers: Record<string, string> = { Accept: 'application/json' }

  if (body !== undefined && !isFormData) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${config.apiBaseUrl}${path}`, {
    method,
    headers,
    signal,
    body: isFormData ? body : body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    const parsed = (await response.json().catch(() => null)) as ApiError | null
    throw new HttpError(response.status, parsed)
  }

  // 204 No Content has no body to deserialize.
  if (response.status === 204) return undefined as T

  return (await response.json()) as T
}

export const http = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>('GET', path, undefined, signal),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>('POST', path, body, signal),
  put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>('PUT', path, body, signal),
  patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>('PATCH', path, body, signal),
  delete: <T>(path: string, signal?: AbortSignal) => request<T>('DELETE', path, undefined, signal),
}
