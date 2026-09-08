import { ref } from 'vue'
import { defineStore } from 'pinia'
import { HttpError } from '@/services/http'
import { listExamples } from '../services/example.api'
import type { ExampleItem } from '../types'

export const useExampleStore = defineStore('example', () => {
  const items = ref<ExampleItem[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const page = await listExamples()
      items.value = page.items
    } catch (cause) {
      error.value = cause instanceof HttpError ? cause.message : 'Failed to load the list.'
    } finally {
      loading.value = false
    }
  }

  return { items, loading, error, fetchAll }
})
