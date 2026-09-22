import { apiClient } from '@/services/api'
import type { EventoEtapa, EventoEstado, EventoResultado, StatusJob } from '@/types/api'

interface HandlersAcompanhamento {
  onEstado(evento: EventoEstado): void
  onEtapa(evento: EventoEtapa): void
  onResultado(evento: EventoResultado): void
  onReconciliar(): void
  onStatusConexao(status: 'conectando' | 'aberta' | 'reconectando'): void
}

const STATUS_TERMINAIS: ReadonlySet<StatusJob> = new Set([
  'liberado',
  'cancelado',
  'arquivado',
  'erro',
])

export function abrirAcompanhamentoJob(idJob: string, handlers: HandlersAcompanhamento) {
  let eventSource: EventSource | null = null
  let timerReconexao: ReturnType<typeof setTimeout> | null = null
  let tentativasBackoff = 0
  let jaConectouAlgumaVez = false
  let ultimaSimulacaoIdProcessada: string | null = null
  let jobEmEstadoTerminal = false
  let fechado = false

  function abrirConexao() {
    if (fechado) return
    if (jaConectouAlgumaVez) handlers.onReconciliar()
    else handlers.onStatusConexao('conectando')

    const conexao = new EventSource(apiClient.acompanharJob(idJob))
    eventSource = conexao
    const ativa = () => !fechado && eventSource === conexao

    conexao.addEventListener('estado', (evento: MessageEvent) => {
      if (!ativa()) return
      try {
        const dados = JSON.parse(evento.data) as EventoEstado
        if (dados.job_id !== idJob) return
        jobEmEstadoTerminal = STATUS_TERMINAIS.has(dados.status)
        handlers.onEstado(dados)
      } catch {
        // Um evento malformado não deve interromper o acompanhamento.
      }
    })
    conexao.addEventListener('etapa', (evento: MessageEvent) => {
      if (!ativa()) return
      try {
        const dados = JSON.parse(evento.data) as EventoEtapa
        if (dados.job_id === idJob) handlers.onEtapa(dados)
      } catch {
        // Um evento malformado não deve interromper o acompanhamento.
      }
    })
    conexao.addEventListener('resultado', (evento: MessageEvent) => {
      if (!ativa()) return
      try {
        const dados = JSON.parse(evento.data) as EventoResultado
        if (dados.job_id === idJob && ultimaSimulacaoIdProcessada !== dados.simulacao_id) {
          ultimaSimulacaoIdProcessada = dados.simulacao_id
          handlers.onResultado(dados)
        }
      } catch {
        // Um evento malformado não deve interromper o acompanhamento.
      }
    })
    conexao.onopen = () => {
      if (!ativa()) return
      jaConectouAlgumaVez = true
      tentativasBackoff = 0
      handlers.onStatusConexao('aberta')
    }
    conexao.onerror = () => {
      if (!ativa()) return
      conexao.close()
      eventSource = null
      // O fechamento pelo servidor após um estado terminal também dispara onerror.
      if (jobEmEstadoTerminal) return
      handlers.onStatusConexao('reconectando')
      const delay = Math.min(1000 * Math.pow(2, tentativasBackoff++), 30000) + Math.random() * 200
      timerReconexao = setTimeout(abrirConexao, delay)
    }
  }

  function fechar() {
    fechado = true
    if (timerReconexao) clearTimeout(timerReconexao)
    eventSource?.close()
    eventSource = null
  }

  abrirConexao()
  return { fechar }
}
