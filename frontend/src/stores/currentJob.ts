import { ref } from 'vue'
import { defineStore } from 'pinia'

/* Esboço do estado global do job atual. REST e SSE serão integrados em tarefas posteriores. */
export const usarStoreJobAtual = defineStore('current-job', () => {
  const idJob = ref<string | null>(null)

  return { idJob }
})
