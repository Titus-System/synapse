import { apiClient } from '@/services/api'
import type { EventoEtapa, EventoEstado, EventoResultado, Job, StatusJob } from '@/types/api'

interface HandlersAcompanhamento {
  onEstado(evento: EventoEstado): void
  onEtapa(evento: EventoEtapa): void
  onResultado(evento: EventoResultado): void
  onReconciliar(job: Job): void
  onStatusConexao(status: 'conectando' | 'aberta' | 'reconectando'): void
}

interface ConexaoSSE {
  fechar(): void
}

const BACKOFF_BASE_MS = 1000
const BACKOFF_FATOR = 2
const BACKOFF_MAXIMO_MS = 30000

// Espelha os estados terminais do contrato (openapi.yaml, StatusJob): o servidor fecha o
// stream sozinho ao atingi-los. O EventSource nativo não distingue esse fechamento limpo de
// uma queda de rede — os dois disparam `onerror` — então é preciso reconhecer o evento
// `estado` terminal para não reconectar indefinidamente contra um job que já terminou.
const STATUS_TERMINAIS: ReadonlySet<StatusJob> = new Set(['liberado', 'cancelado', 'arquivado', 'erro'])

function calcularDelayReconexao(tentativasBackoff: number): number {
  const delayExponencial = BACKOFF_BASE_MS * Math.pow(BACKOFF_FATOR, tentativasBackoff - 1)
  const delaySaturado = Math.min(delayExponencial, BACKOFF_MAXIMO_MS)
  const jitter = Math.random() * 200
  return delaySaturado + jitter
}

/**
 * Abre o stream SSE `GET /jobs/{id}/events` e mantém a conexão viva (reconectando sozinha) até
 * `fechar()` ser chamado. Não decide o que fazer com os dados: é transporte puro — desserializa
 * cada evento e repassa ao handler correspondente em `handlers`, fornecido por quem chama. Quem
 * decide o destino final (store, log, o que for) é o chamador, não esta função; hoje quem chama é
 * `usarStoreJobAtual` (src/stores/currentJob.ts), que implementa os handlers escrevendo em refs.
 */
export function abrirAcompanhamentoJob(idJob: string, handlers: HandlersAcompanhamento): ConexaoSSE {
  let eventSource: EventSource | null = null
  let timerReconexao: ReturnType<typeof setTimeout> | null = null
  // Conta erros consecutivos para calcular o backoff; reseta a cada conexão aberta com sucesso.
  let tentativasBackoff = 0
  // Diferente de tentativasBackoff, nunca reseta. Distingue a primeira conexão (sem reconciliação
  // REST, o snapshot "estado" do próprio stream já cobre) de toda reabertura seguinte (reconciliação
  // necessária porque eventos podem ter se perdido durante a desconexão).
  let jaConectouAlgumaVez = false
  let ultimaSimulacaoIdProcessada: string | null = null
  // Marcado quando um evento `estado` chega com status terminal. Depois disso, o próximo
  // `onerror` é o fechamento esperado do servidor (não uma queda), então não reconecta.
  let jobEmEstadoTerminal = false

  function reconciliar() {
    apiClient
      .consultarJob(idJob)
      .then((job) => {
        handlers.onReconciliar(job)
      })
      .catch(() => {
        // Falha de reconciliação é best-effort; o próximo evento `estado` do stream recupera o status.
      })
  }

  function abrirConexao() {
    if (jaConectouAlgumaVez) {
      reconciliar()
    } else {
      handlers.onStatusConexao('conectando')
    }

    const url = apiClient.acompanharJob(idJob)
    eventSource = new EventSource(url)

    eventSource.addEventListener('estado', (evento: MessageEvent) => {
      try {
        const dados = JSON.parse(evento.data) as EventoEstado
        if (STATUS_TERMINAIS.has(dados.status)) {
          jobEmEstadoTerminal = true
        }
        handlers.onEstado(dados)
      } catch {
        // Dados inválidos; ignora silenciosamente
      }
    })

    eventSource.addEventListener('etapa', (evento: MessageEvent) => {
      try {
        const dados = JSON.parse(evento.data) as EventoEtapa
        handlers.onEtapa(dados)
      } catch {
        // Dados inválidos; ignora silenciosamente
      }
    })

    eventSource.addEventListener('resultado', (evento: MessageEvent) => {
      try {
        const dados = JSON.parse(evento.data) as EventoResultado
        if (ultimaSimulacaoIdProcessada !== dados.simulacao_id) {
          ultimaSimulacaoIdProcessada = dados.simulacao_id
          handlers.onResultado(dados)
        }
      } catch {
        // Dados inválidos; ignora silenciosamente
      }
    })

    eventSource.onopen = () => {
      jaConectouAlgumaVez = true
      tentativasBackoff = 0
      handlers.onStatusConexao('aberta')
    }

    eventSource.onerror = () => {
      if (eventSource) {
        eventSource.close()
        eventSource = null
      }

      if (jobEmEstadoTerminal) {
        // Fechamento esperado: o job já terminou e o servidor encerrou o stream por contrato
        return
      }

      handlers.onStatusConexao('reconectando')
      tentativasBackoff += 1
      const delayMs = calcularDelayReconexao(tentativasBackoff)
      timerReconexao = setTimeout(abrirConexao, delayMs)
    }
  }

  function fechar() {
    if (timerReconexao) {
      clearTimeout(timerReconexao)
      timerReconexao = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  abrirConexao()

  return { fechar }
}
