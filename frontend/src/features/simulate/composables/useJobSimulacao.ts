import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { storeToRefs } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { regraMaisRecente, simulacaoVisivel } from '@/services/job'
import type { Simulacao } from '@/types/api'
import { usarStoreJobAtual } from '@/stores/currentJob'
import { observarAceiteMeta } from '../services/aceitarMetaLogging'

export function useJobSimulacao(jobId: MaybeRefOrGetter<string>) {
  const store = usarStoreJobAtual()
  const { job, carregando, etapaAtual, estadoConexao, motivoParada, reconciliandoSugestao } =
    storeToRefs(store)
  const erroAcao = ref<HttpError | null>(null)
  const acaoProcessando = ref(false)
  let ciclo = 0

  const status = computed(() => job.value?.status ?? store.statusAtual)
  const buscandoMeta = computed(
    () =>
      !!job.value && 'busca_meta_em_curso' in job.value && job.value.busca_meta_em_curso === true,
  )
  const processando = computed(
    () =>
      carregando.value ||
      reconciliandoSugestao.value ||
      buscandoMeta.value ||
      ['aguardando_transcricao', 'gerando_regra', 'simulando'].includes(status.value ?? ''),
  )
  const ultimaRegra = computed(() => regraMaisRecente(job.value?.regras ?? []))
  const sugestao = computed(() =>
    ultimaRegra.value?.origem === 'sugestao_adaptacao' ? ultimaRegra.value : undefined,
  )
  const regra = computed(() =>
    sugestao.value
      ? regraMaisRecente(
          (job.value?.regras ?? []).filter((item) => item.origem !== 'sugestao_adaptacao'),
        )
      : ultimaRegra.value,
  )
  function simulacaoDaRegra(regraId: string | undefined): Simulacao | null {
    if (!regraId) return null
    const atual = job.value
    if (atual?.simulacao?.regra_id === regraId) return atual.simulacao
    return (
      atual?.simulacoes?.reduce<Simulacao | null>(
        (encontrada, item) => (item.regra_id === regraId ? item : encontrada),
        null,
      ) ?? null
    )
  }
  const simulacao = computed(() =>
    processando.value
      ? null
      : sugestao.value
        ? simulacaoDaRegra(regra.value?.id)
        : simulacaoVisivel(job.value),
  )
  const simulacaoSugestao = computed(() => {
    if (processando.value || status.value !== 'aguardando_decisao_usuario') return null
    const vigente = simulacaoVisivel(job.value)
    return vigente?.regra_id === sugestao.value?.id &&
      vigente?.status === 'sucesso' &&
      vigente.veredito === 'viavel'
      ? vigente
      : null
  })
  const falha = computed(() => store.erro)
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
    () =>
      status.value === 'aguardando_decisao_usuario' && !acaoProcessando.value && !processando.value,
  )
  const metaSugerida = computed(() =>
    !processando.value &&
    status.value === 'aguardando_decisao_usuario' &&
    job.value?.orcamento != null
      ? job.value.meta_sugerida
      : undefined,
  )
  const podeAceitarMeta = computed(
    () => !!metaSugerida.value && 'meta_venda' in metaSugerida.value && !acaoProcessando.value,
  )
  const mensagemErroAcao = computed(() =>
    erroAcao.value
      ? erroAcao.value.status === 409
        ? 'Esta opção mudou. Confira o resultado atualizado antes de continuar.'
        : 'Não foi possível concluir a ação. Tente novamente.'
      : null,
  )

  async function aceitarMeta(): Promise<void> {
    if (!podeAceitarMeta.value) return
    const id = toValue(jobId)
    const atual = ciclo
    acaoProcessando.value = true
    erroAcao.value = null
    try {
      const atualizado = await observarAceiteMeta(id, () =>
        apiClient.executarAcao(id, { acao: 'aceitar_meta' }),
      )
      if (atual !== ciclo) return
      store.aplicarJob(atualizado)
      await store.consultarJob()
    } catch (falha) {
      if (atual !== ciclo) return
      erroAcao.value = falha instanceof HttpError ? falha : new HttpError(0, '')
      if (erroAcao.value.status === 409) await store.consultarJob()
    } finally {
      if (atual === ciclo) acaoProcessando.value = false
    }
  }

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
    processando,
    buscandoMeta,
    metaSugerida,
    podeAceitarMeta,
    aceitarMeta,
    mensagemErroAcao,
    cancelar,
    consultarJob: store.consultarJob,
    iniciar,
    parar,
  }
}
