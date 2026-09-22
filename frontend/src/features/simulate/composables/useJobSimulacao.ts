import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { storeToRefs } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { regraMaisRecente, simulacaoVisivel } from '@/services/job'
import { usarStoreJobAtual } from '@/stores/currentJob'

export function useJobSimulacao(jobId: MaybeRefOrGetter<string>) {
  const store = usarStoreJobAtual()
  const { job, carregando, etapaAtual, estadoConexao } = storeToRefs(store)
  const erroAcao = ref<HttpError | null>(null)
  const acaoProcessando = ref(false)
  let ciclo = 0

  const status = computed(() => job.value?.status ?? store.statusAtual)
  const regra = computed(() => regraMaisRecente(job.value?.regras ?? []))
  const simulacao = computed(() => simulacaoVisivel(job.value))
  const sugestao = computed(() =>
    regra.value?.origem === 'sugestao_adaptacao' ? regra.value : undefined,
  )
  const falha = computed(() => erroAcao.value ?? store.erro)
  const erro = computed(
    () =>
      falha.value?.message ??
      (status.value === 'erro' ? 'Não foi possível concluir o processamento desta regra.' : null),
  )
  const erroStatus = computed(() => falha.value?.status ?? null)
  const erroCodigo = computed(() => falha.value?.code ?? null)
  const erroEspecifico = computed(() => erro.value !== null)
  const aguardandoConfirmacao = computed(() => status.value === 'aguardando_confirmacao_parametros')
  const simulacaoInviavel = computed(() => simulacao.value?.veredito === 'inviavel')
  const resultadoDisponivel = computed(() => simulacao.value?.resultado != null)
  const podeAceitarSugestao = computed(
    () =>
      !acaoProcessando.value &&
      !!sugestao.value &&
      ['simulacao_inviavel', 'aguardando_confirmacao_parametros'].includes(status.value ?? ''),
  )
  const podeCancelar = computed(
    () =>
      !acaoProcessando.value &&
      [
        'aguardando_confirmacao_parametros',
        'simulacao_inviavel',
        'aguardando_decisao_usuario',
      ].includes(status.value ?? ''),
  )
  const podeFinalizar = computed(
    () => status.value === 'aguardando_decisao_usuario' && !acaoProcessando.value,
  )

  async function executar(acao: 'aceitar' | 'cancelar'): Promise<boolean> {
    if (acao === 'aceitar' ? !podeAceitarSugestao.value : !podeCancelar.value) return false
    const id = toValue(jobId)
    const atual = ciclo
    acaoProcessando.value = true
    erroAcao.value = null
    try {
      if (acao === 'aceitar' && sugestao.value) {
        const confirmado = await apiClient.confirmarParametros(id, {
          regra: sugestao.value.representacao,
        })
        if (atual !== ciclo) return false
        store.aplicarConfirmacao(confirmado)
      } else {
        const cancelado = await apiClient.executarAcao(id, { acao: 'cancelar' })
        if (atual !== ciclo) return false
        store.aplicarJob(cancelado)
      }
      void store.consultarJob()
      return atual === ciclo
    } catch (falha) {
      if (atual !== ciclo) return false
      erroAcao.value =
        falha instanceof HttpError
          ? falha
          : new HttpError(0, 'Não foi possível concluir a ação. Tente novamente.')
      if (erroAcao.value.status === 409) await store.consultarJob()
      return false
    } finally {
      if (atual === ciclo) acaoProcessando.value = false
    }
  }

  async function iniciar() {
    ciclo += 1
    acaoProcessando.value = false
    erroAcao.value = null
    await store.iniciarAcompanhamento(toValue(jobId))
  }

  function parar() {
    ciclo += 1
    store.pararAcompanhamento()
  }

  return {
    job,
    regra,
    sugestao,
    simulacao,
    status,
    carregando,
    erro,
    erroStatus,
    erroCodigo,
    erroEspecifico,
    etapaAtual,
    estadoConexao,
    aguardandoConfirmacao,
    simulacaoInviavel,
    resultadoDisponivel,
    podeAceitarSugestao,
    podeCancelar,
    podeFinalizar,
    acaoProcessando,
    aceitarSugestao: () => executar('aceitar'),
    cancelar: () => executar('cancelar'),
    consultarJob: store.consultarJob,
    iniciar,
    parar,
  }
}
