import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { storeToRefs } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { regraMaisRecente, simulacaoVisivel } from '@/services/job'
import type { Simulacao } from '@/types/api'
import { usarStoreJobAtual } from '@/stores/currentJob'

export function useJobSimulacao(jobId: MaybeRefOrGetter<string>) {
  const store = usarStoreJobAtual()
  const { job, carregando, etapaAtual, estadoConexao, motivoParada } = storeToRefs(store)
  const erroAcao = ref<HttpError | null>(null)
  const acaoProcessando = ref(false)
  let ciclo = 0

  const status = computed(() => job.value?.status ?? store.statusAtual)
  const ultimaRegra = computed(() => regraMaisRecente(job.value?.regras ?? []))
  const sugestao = computed(() =>
    ultimaRegra.value?.origem === 'sugestao_adaptacao' ? ultimaRegra.value : undefined,
  )
  const regra = computed(() => sugestao.value
    ? regraMaisRecente((job.value?.regras ?? []).filter((item) => item.versao < sugestao.value!.versao))
    : ultimaRegra.value,
  )
  function simulacaoDaRegra(regraId: string | undefined): Simulacao | null {
    if (!regraId) return null
    const atual = job.value
    return atual?.simulacoes?.reduce<Simulacao | null>((encontrada, item) =>
      item.regra_id === regraId ? item : encontrada, null)
      ?? (atual?.simulacao?.regra_id === regraId ? atual.simulacao : null)
  }
  const simulacao = computed(() =>
    sugestao.value
      ? simulacaoDaRegra(regra.value?.id)
      : simulacaoVisivel(job.value),
  )
  const simulacaoSugestao = computed(() => simulacaoDaRegra(sugestao.value?.id))
  const falha = computed(() => erroAcao.value ?? store.erro)
  // Falha de carregamento e job interrompido são desfechos diferentes: o primeiro
  // é a tela que não conseguiu ler o job, o segundo é o job que parou.
  const erro = computed(() => falha.value?.message ?? null)
  const processamentoInterrompido = computed(() => status.value === 'erro')
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
      status.value === 'aguardando_decisao_usuario' &&
      simulacaoSugestao.value?.status === 'sucesso' &&
      simulacaoSugestao.value.veredito === 'viavel',
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

  async function cancelar(): Promise<boolean> {
    if (!podeCancelar.value) return false
    const id = toValue(jobId)
    const atual = ciclo
    acaoProcessando.value = true
    erroAcao.value = null
    try {
      const cancelado = await apiClient.executarAcao(id, { acao: 'cancelar' })
      if (atual !== ciclo) return false
      store.aplicarJob(cancelado)
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
    simulacaoSugestao,
    status,
    carregando,
    erro,
    erroStatus,
    erroCodigo,
    erroEspecifico,
    etapaAtual,
    estadoConexao,
    aguardandoConfirmacao,
    processamentoInterrompido,
    motivoParada,
    simulacaoInviavel,
    resultadoDisponivel,
    podeAceitarSugestao,
    podeCancelar,
    podeFinalizar,
    acaoProcessando,
    cancelar,
    consultarJob: store.consultarJob,
    iniciar,
    parar,
  }
}
