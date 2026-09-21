import { computed, onBeforeUnmount, ref } from 'vue'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type {
  EventoEtapa,
  EventoEstado,
  EventoResultado,
  Job,
  CodigoErro,
} from '@/types/api'

const ESTADOS_TERMINAIS = new Set([
  'liberado',
  'cancelado',
  'arquivado',
  'erro',
])

export function useJobSimulacao(jobId: string) {
  const job = ref<Job | null>(null)
  const carregando = ref(true)
  const erro = ref<string | null>(null)
  const erroStatus = ref<number | null>(null)
  const erroCodigo = ref<CodigoErro | null>(null)
  const erroEspecifico = ref(false)
  const etapaAtual = ref<EventoEtapa | null>(null)

  const eventos: EventSource | null = null
  const reconectando = false

  const status = computed(() => job.value?.status ?? null)

  const aguardandoConfirmacao = computed(
    () => status.value === 'aguardando_confirmacao_parametros',
  )

  const simulacaoInviavel = computed(
    () => job.value?.simulacao?.veredito === 'inviavel',
  )

  const resultadoDisponivel = computed(
    () => job.value?.simulacao?.resultado != null,
  )

  async function consultarJob(): Promise<Job | null> {
  erro.value = null
  erroStatus.value = null
  erroCodigo.value = null
  erroEspecifico.value = false

  try {
    const resultado = await apiClient.consultarJob(jobId)
    job.value = resultado
    carregando.value = false
    return resultado
  } catch (error) {
        erro.value =
          error instanceof Error
            ? error.message
            : 'Não foi possível consultar o processamento.'

        if (error instanceof HttpError) {
          erroStatus.value = error.status
          erroCodigo.value = error.code ?? null
          erroEspecifico.value = true
        } else {
          erroStatus.value = null
          erroCodigo.value = null
          erroEspecifico.value = false
        }

        carregando.value = false
        return null
      }
  }

  async function iniciar(): Promise<void> {
    carregando.value = true
    await consultarJob()
  }

  return {
    job,
    status,
    carregando,
    erro,
    erroStatus,
    erroCodigo,
    erroEspecifico,
    etapaAtual,
    aguardandoConfirmacao,
    simulacaoInviavel,
    resultadoDisponivel,
    consultarJob,
    iniciar,
  }
}
