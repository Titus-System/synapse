import { ref } from 'vue'
import { defineStore } from 'pinia'

/* Esboço do estado global de sessão. A autenticação será introduzida na T-071. */
export const usarStoreSessao = defineStore('session', () => {
  const estaAutenticado = ref(false)

  return { estaAutenticado }
})
