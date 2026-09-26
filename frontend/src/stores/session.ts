import { ref } from 'vue'
import { defineStore } from 'pinia'
import { iniciarLogin, iniciarLogout, inicializarKeycloak, limparTokenDoKeycloak } from '@/services/keycloak'

export const usarStoreSessao = defineStore('sessao', () => {
  const estaAutenticado = ref(false)
  const inicializando = ref(false)
  const indisponivel = ref(false)

  async function inicializar(): Promise<void> {
    inicializando.value = true
    indisponivel.value = false
    try {
      estaAutenticado.value = await inicializarKeycloak()
    } catch {
      estaAutenticado.value = false
      indisponivel.value = true
    } finally {
      inicializando.value = false
    }
  }

  async function entrar(caminhoDeRetorno?: string): Promise<void> {
    await iniciarLogin(caminhoDeRetorno)
  }

  async function sair(): Promise<void> {
    estaAutenticado.value = false
    await iniciarLogout()
  }

  function encerrarPorSessaoInvalida(): void {
    limparTokenDoKeycloak()
    estaAutenticado.value = false
  }

  return { estaAutenticado, inicializando, indisponivel, inicializar, entrar, sair, encerrarPorSessaoInvalida }
})
