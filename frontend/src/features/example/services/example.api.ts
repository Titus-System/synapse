import { http } from '@/services/http'
import type { Paginated } from '@/types/api'
import type { ExampleItem } from '../types'

export function listExamples(signal?: AbortSignal) {
  return http.get<Paginated<ExampleItem>>('/examples', signal)
}

export function getExample(id: string, signal?: AbortSignal) {
  return http.get<ExampleItem>(`/examples/${id}`, signal)
}
