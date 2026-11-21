import { ref } from 'vue'
import { defineStore } from 'pinia'
import {
  iniciarLogin,
  iniciarLogout,
  inicializarKeycloak,
  limparTokenDoKeycloak,
  obterPapelDeNegocio,
  obterLoginDoUsuario,
  type PapelDeNegocio,
} from '@/services/keycloak'

export const usarStoreSessao = defineStore('sessao', () => {
  const papel = ref<PapelDeNegocio>()
  const login = ref<string>()
  const estaAutenticado = ref(false)
  const inicializando = ref(false)
  const indisponivel = ref(false)

  async function inicializar(): Promise<void> {
    inicializando.value = true
    indisponivel.value = false
    papel.value = undefined
    login.value = undefined
    try {
      estaAutenticado.value = await inicializarKeycloak()
      if (estaAutenticado.value) {
        papel.value = obterPapelDeNegocio()
        login.value = obterLoginDoUsuario()
      }
    } catch {
      estaAutenticado.value = false
      papel.value = undefined
      login.value = undefined
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
    papel.value = undefined
    login.value = undefined
    await iniciarLogout()
  }

  function encerrarPorSessaoInvalida(): void {
    limparTokenDoKeycloak()
    estaAutenticado.value = false
    papel.value = undefined
    login.value = undefined
  }

  return {
    papel,
    login,
    estaAutenticado,
    inicializando,
    indisponivel,
    inicializar,
    entrar,
    sair,
    encerrarPorSessaoInvalida,
  }
})
