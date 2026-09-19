import { computed, onBeforeUnmount, ref } from 'vue'
import { apiClient } from '@/services/api'
import type {
  EventoEtapa,
  EventoEstado,
  EventoResultado,
  Job,
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
  const etapaAtual = ref<EventoEtapa | null>(null)

  let eventos: EventSource | null = null
  let reconectando = false

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
    try {
      const resultado = await apiClient.consultarJob(jobId)
      job.value = resultado
      return resultado
    } catch (error) {
      erro.value =
        error instanceof Error
          ? error.message
          : 'Não foi possível consultar o processamento.'
      return null
    }
  }

  function fecharStream(): void {
    eventos?.close()
    eventos = null
  }

  function conectarStream(): void {
    if (!jobId || eventos || reconectando) return

    erro.value = null
    eventos = new EventSource(apiClient.acompanharJob(jobId))

    eventos.addEventListener('estado', async (evento) => {
      const dados: EventoEstado = JSON.parse(evento.data)

      if (dados.status === 'aguardando_confirmacao_parametros') {
        await consultarJob()
        carregando.value = false
        return
      }

      if (ESTADOS_TERMINAIS.has(dados.status)) {
        const resultado = await consultarJob()
        carregando.value = false

        if (resultado) {
          fecharStream()
        }
      }
    })

    eventos.addEventListener('etapa', (evento) => {
      const dados: EventoEtapa = JSON.parse(evento.data)

      etapaAtual.value = dados
    })

    eventos.addEventListener('resultado', async (evento) => {
      const dados: EventoResultado = JSON.parse(evento.data)

      console.log('Resultado da simulação recebido:', dados)

      await consultarJob()
      carregando.value = false
    })

    eventos.onerror = () => {
      if (!eventos) return

      fecharStream()

      if (reconectando) return

      reconectando = true

      window.setTimeout(() => {
        reconectando = false

        if (!eventos) {
          conectarStream()
        }
      }, 1000)
    }
  }

  async function iniciar(): Promise<void> {
    carregando.value = true
    erro.value = null

    conectarStream()
  }

  onBeforeUnmount(() => {
    fecharStream()
  })

  return {
    job,
    status,
    carregando,
    erro,
    etapaAtual,
    aguardandoConfirmacao,
    simulacaoInviavel,
    resultadoDisponivel,
    consultarJob,
    conectarStream,
    iniciar,
  }
}
