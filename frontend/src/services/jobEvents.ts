import { apiClient } from '@/services/api'
import { http } from '@/services/http'
import { consumirEventosSse } from '@/services/sse'
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
  let conexaoAtual: AbortController | null = null
  let timerReconexao: ReturnType<typeof setTimeout> | null = null
  let tentativasBackoff = 0
  let jaConectouAlgumaVez = false
  let ultimaSimulacaoIdProcessada: string | null = null
  let jobEmEstadoTerminal = false
  let fechado = false

  function receberEvento(evento: string, dados: string) {
    try {
      switch (evento) {
        case 'estado': {
          const estado = JSON.parse(dados) as EventoEstado
          if (estado.job_id !== idJob) return
          jobEmEstadoTerminal = STATUS_TERMINAIS.has(estado.status)
          handlers.onEstado(estado)
          break
        }
        case 'etapa': {
          const etapa = JSON.parse(dados) as EventoEtapa
          if (etapa.job_id === idJob) handlers.onEtapa(etapa)
          break
        }
        case 'resultado': {
          const resultado = JSON.parse(dados) as EventoResultado
          if (resultado.job_id === idJob && resultado.simulacao_id !== ultimaSimulacaoIdProcessada) {
            ultimaSimulacaoIdProcessada = resultado.simulacao_id
            handlers.onResultado(resultado)
          }
          break
        }
      }
    } catch {
      // Um evento malformado não deve interromper o acompanhamento.
    }
  }

  async function abrirConexao() {
    if (fechado) return
    if (jaConectouAlgumaVez) handlers.onReconciliar()
    else handlers.onStatusConexao('conectando')

    const conexao = new AbortController()
    conexaoAtual = conexao
    const ativa = () => !fechado && conexaoAtual === conexao

    try {
      const corpo = await http.stream(apiClient.acompanharJob(idJob), conexao.signal)
      if (!ativa()) {
        await corpo.cancel()
        return
      }
      jaConectouAlgumaVez = true
      tentativasBackoff = 0
      handlers.onStatusConexao('aberta')
      await consumirEventosSse(corpo, (evento, dados) => {
        if (ativa()) receberEvento(evento, dados)
      })
    } catch {
      // A reconexão também recupera quedas durante a leitura do corpo da resposta.
    }

    if (!ativa()) return
    conexao.abort()
    conexaoAtual = null
    if (jobEmEstadoTerminal) return
    handlers.onStatusConexao('reconectando')
    const delay = Math.min(1000 * Math.pow(2, tentativasBackoff++), 30000) + Math.random() * 200
    timerReconexao = setTimeout(() => void abrirConexao(), delay)
  }

  function fechar() {
    fechado = true
    if (timerReconexao) clearTimeout(timerReconexao)
    conexaoAtual?.abort()
    conexaoAtual = null
  }

  void abrirConexao()
  return { fechar }
}
