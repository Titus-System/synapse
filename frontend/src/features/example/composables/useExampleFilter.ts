import { computed, ref, type Ref } from 'vue'
import type { ExampleItem } from '../types'

export function useExampleFilter(source: Ref<ExampleItem[]>) {
  const term = ref('')

  const filtered = computed(() => {
    const query = term.value.trim().toLowerCase()
    if (query === '') return source.value
    return source.value.filter((item) => item.name.toLowerCase().includes(query))
  })

  return { term, filtered }
}
