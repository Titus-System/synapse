import { onBeforeUnmount, ref, shallowRef, watch, type Ref } from 'vue'
import { HttpError } from '@/services/http'
import type { DetalhamentoSimulacao } from '@/types/api'

export function useDetalhamento(
  identidade: Ref<string>,
  consultar: (signal: AbortSignal) => Promise<DetalhamentoSimulacao>,
) {
  const aberto = ref(false)
  const carregando = ref(false)
  const erro = ref<string | null>(null)
  const resposta = shallowRef<DetalhamentoSimulacao | null>(null)
  let requisicao: AbortController | undefined

  function limpar() {
    requisicao?.abort()
    requisicao = undefined
    aberto.value = false
    carregando.value = false
    erro.value = null
    resposta.value = null
  }

  async function carregar() {
    if (carregando.value || resposta.value) return
    const controle = new AbortController()
    requisicao = controle
    carregando.value = true
    erro.value = null
    try {
      const resultado = await consultar(controle.signal)
      if (requisicao === controle) resposta.value = resultado
    } catch (falha) {
      if (requisicao !== controle || controle.signal.aborted) return
      erro.value =
        falha instanceof HttpError
          ? falha.message
          : 'Não foi possível carregar o relatório. Tente novamente.'
    } finally {
      if (requisicao === controle) carregando.value = false
    }
  }

  function alternar() {
    aberto.value = !aberto.value
    if (aberto.value) void carregar()
  }

  watch(identidade, limpar, { flush: 'sync' })
  onBeforeUnmount(limpar)
  return { aberto, carregando, erro, resposta, alternar, carregar }
}
