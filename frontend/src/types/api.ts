/** Paginated listing envelope. Adjust to the backend's actual format. */
export interface Paginated<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}

/** Error body returned by the API. Adjust to the backend's actual format. */
export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown>
}
