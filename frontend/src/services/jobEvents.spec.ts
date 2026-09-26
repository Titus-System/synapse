import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { abrirAcompanhamentoJob } from './jobEvents'
import { apiClient } from './api'
import { http } from './http'
import { flushPromises } from '@vue/test-utils'
import type { EventoEtapa, EventoEstado, EventoResultado } from '@/types/api'

vi.mock('./api', () => ({
  apiClient: {
    acompanharJob: vi.fn<(id: string) => string>((id) => `/api/jobs/${id}/events`),
  },
}))

vi.mock('./http', () => ({
  http: { stream: vi.fn<(url: string, signal: AbortSignal) => Promise<ReadableStream<Uint8Array>>>() },
}))

class StreamSimulado {
  static instances: StreamSimulado[] = []
  private resolver!: (corpo: ReadableStream<Uint8Array>) => void
  private rejeitar!: (erro: Error) => void
  readonly resposta = new Promise<ReadableStream<Uint8Array>>((resolve, reject) => {
    this.resolver = resolve
    this.rejeitar = reject
  })
  private controlador!: ReadableStreamDefaultController<Uint8Array>
  private corpo = new ReadableStream<Uint8Array>({
    start: (controlador) => { this.controlador = controlador },
  })
  fechada = false

  constructor(readonly url: string, signal: AbortSignal) {
    StreamSimulado.instances.push(this)
    signal.addEventListener('abort', () => {
      this.fechada = true
      const erro = new DOMException('Cancelado', 'AbortError')
      this.rejeitar(erro)
      this.controlador.error(erro)
    }, { once: true })
  }

  async emitir(evento: string, dados: unknown) {
    await this.emitirBruto(evento, JSON.stringify(dados))
  }

  async emitirBruto(evento: string, dados: string) {
    if (this.fechada) return
    await this.abrir()
    this.controlador.enqueue(new TextEncoder().encode(`event: ${evento}\ndata: ${dados}\n\n`))
    await flushPromises()
  }

  async abrir() {
    this.resolver(this.corpo)
    await flushPromises()
  }

  async errar() {
    const erro = new Error('Conexão interrompida')
    this.rejeitar(erro)
    this.controlador.error(erro)
    await flushPromises()
  }

  async concluir() {
    this.controlador.close()
    await flushPromises()
  }
}

function novosHandlers() {
  return {
    onStatusConexao: vi.fn<(status: 'conectando' | 'aberta' | 'reconectando') => void>(),
    onEstado: vi.fn<(evento: EventoEstado) => void>(),
    onEtapa: vi.fn<(evento: EventoEtapa) => void>(),
    onResultado: vi.fn<(evento: EventoResultado) => void>(),
    onReconciliar: vi.fn<() => void>(),
  }
}

describe('jobEvents', () => {
  beforeEach(() => {
    StreamSimulado.instances = []
    vi.mocked(http.stream).mockImplementation((url, signal) => new StreamSimulado(url, signal).resposta)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  function instanciaAtual(): StreamSimulado {
    const instancia = StreamSimulado.instances[StreamSimulado.instances.length - 1]
    if (!instancia) throw new Error('Nenhum stream foi criado')
    return instancia
  }

  it('abre o stream com a URL de apiClient.acompanharJob', async () => {
    abrirAcompanhamentoJob('job-123', novosHandlers())

    expect(apiClient.acompanharJob).toHaveBeenCalledWith('job-123')
    expect(instanciaAtual().url).toBe('/api/jobs/job-123/events')
  })

  it('sinaliza conectando na primeira abertura, sem reconciliar', async () => {
    const handlers = novosHandlers()

    abrirAcompanhamentoJob('job-123', handlers)

    expect(handlers.onStatusConexao).toHaveBeenCalledWith('conectando')
    expect(handlers.onReconciliar).not.toHaveBeenCalled()
  })

  it('sinaliza aberta quando o servidor abre o stream', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    await instanciaAtual().abrir()

    expect(handlers.onStatusConexao).toHaveBeenLastCalledWith('aberta')
  })

  it('despacha o evento estado desserializado para o handler', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoEstado = {
      job_id: 'job-123',
      status: 'simulando',
      status_anterior: 'gerando_regra',
    }
    await instanciaAtual().emitir('estado', evento)

    expect(handlers.onEstado).toHaveBeenCalledWith(evento)
  })

  it('despacha o evento etapa desserializado para o handler', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoEtapa = { job_id: 'job-123', etapa: 'geracao_codigo', status: 'iniciada' }
    await instanciaAtual().emitir('etapa', evento)

    expect(handlers.onEtapa).toHaveBeenCalledWith(evento)
  })

  it('despacha o evento resultado desserializado para o handler', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoResultado = {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
      veredito: 'viavel',
    }
    await instanciaAtual().emitir('resultado', evento)

    expect(handlers.onResultado).toHaveBeenCalledWith(evento)
  })

  it('deduplica resultado repetido com o mesmo simulacao_id', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoResultado = {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
      veredito: 'viavel',
    }

    await instanciaAtual().emitir('resultado', evento)
    await instanciaAtual().emitir('resultado', evento)

    expect(handlers.onResultado).toHaveBeenCalledTimes(1)
  })

  it('não deduplica resultados de simulacoes distintas', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    await instanciaAtual().emitir('resultado', {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
    } satisfies EventoResultado)
    await instanciaAtual().emitir('resultado', {
      job_id: 'job-123',
      simulacao_id: 'sim-2',
      status: 'sucesso',
    } satisfies EventoResultado)

    expect(handlers.onResultado).toHaveBeenCalledTimes(2)
  })

  it('ignora evento com data que não é JSON válido, sem lançar e sem chamar o handler', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    await instanciaAtual().emitirBruto('estado', 'não é JSON')
    expect(handlers.onEstado).not.toHaveBeenCalled()
  })

  it('ao cair a conexão, fecha a requisição e sinaliza reconectando imediatamente', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)
    await instanciaAtual().abrir()

    const instanciaCaida = instanciaAtual()
    await instanciaCaida.errar()

    expect(instanciaCaida.fechada).toBe(true)
    expect(handlers.onStatusConexao).toHaveBeenLastCalledWith('reconectando')
  })

  // Delay = BACKOFF_BASE_MS * FATOR^(tentativa-1) + jitter, jitter ∈ [0, 200).
  // Tentativa 1 ∈ [1000, 1200); tentativa 2 ∈ [2000, 2200).
  const ANTES_DO_MINIMO_TENTATIVA_1 = 999
  const DEPOIS_DO_MAXIMO_TENTATIVA_1 = 1200
  const ANTES_DO_MINIMO_TENTATIVA_2 = 1999
  const DEPOIS_DO_MAXIMO_TENTATIVA_2 = 2200

  it('reabre uma nova conexão após o delay de backoff', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)
    await instanciaAtual().abrir()
    await instanciaAtual().errar()

    expect(StreamSimulado.instances).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_1)
    expect(StreamSimulado.instances).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1 - ANTES_DO_MINIMO_TENTATIVA_1)
    expect(StreamSimulado.instances).toHaveLength(2)
  })

  it('cresce o delay exponencialmente em erros consecutivos sem sucesso entre eles', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    // 1º erro (antes de qualquer onopen): delay base ~1000ms
    await instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_1)
    expect(StreamSimulado.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1 - ANTES_DO_MINIMO_TENTATIVA_1)
    expect(StreamSimulado.instances).toHaveLength(2)

    // 2º erro consecutivo, sem onopen no meio: delay deve dobrar para ~2000ms
    await instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_2)
    expect(StreamSimulado.instances).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_2 - ANTES_DO_MINIMO_TENTATIVA_2)
    expect(StreamSimulado.instances).toHaveLength(3)
  })

  it('reseta o backoff para o valor base após uma reconexão bem-sucedida', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    // 1º erro, reconecta após o delay base
    await instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1)
    expect(StreamSimulado.instances).toHaveLength(2)

    // A nova conexão abre com sucesso, resetando o backoff
    await instanciaAtual().abrir()
    await instanciaAtual().errar()

    // Se o backoff não tivesse resetado, o delay teria dobrado (mínimo ~2000ms) e não
    // dispararia ainda em 1500ms; reconectar aqui prova que voltou ao delay base (~1000-1200ms).
    await vi.advanceTimersByTimeAsync(1500)
    expect(StreamSimulado.instances).toHaveLength(3)
  })

  it('solicita reconciliação ao reabrir a conexão', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)
    expect(handlers.onReconciliar).not.toHaveBeenCalled()
    await instanciaAtual().abrir()
    await instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(1250)
    expect(StreamSimulado.instances).toHaveLength(2)
    expect(handlers.onReconciliar).toHaveBeenCalledOnce()
  })

  it('ignora eventos e erros de uma conexão já fechada', async () => {
    const handlers = novosHandlers()
    const { fechar } = abrirAcompanhamentoJob('job-123', handlers)
    const antiga = instanciaAtual()
    fechar()
    await antiga.emitir('estado', { job_id: 'job-123', status: 'simulando' })
    await antiga.errar()
    await vi.advanceTimersByTimeAsync(60000)
    expect(handlers.onEstado).not.toHaveBeenCalled()
    expect(StreamSimulado.instances).toHaveLength(1)
  })

  it('fechar() encerra a requisição e cancela o timer de reconexão pendente', async () => {
    const handlers = novosHandlers()
    const { fechar } = abrirAcompanhamentoJob('job-123', handlers)
    await instanciaAtual().abrir()
    await instanciaAtual().errar()

    fechar()

    expect(instanciaAtual().fechada).toBe(true)

    await vi.advanceTimersByTimeAsync(5000)
    expect(StreamSimulado.instances).toHaveLength(1)
  })

  describe('encerramento pelo servidor em estado terminal', () => {
    it.each(['liberado', 'cancelado', 'arquivado', 'erro'] as const)(
      'não reconecta depois do evento estado com status terminal %s seguido do fechamento do servidor',
      async (statusTerminal) => {
        const handlers = novosHandlers()
        abrirAcompanhamentoJob('job-123', handlers)
        await instanciaAtual().abrir()

        // Fotografia final: o contrato diz que o servidor manda o estado terminal e fecha.
        await instanciaAtual().emitir('estado', {
          job_id: 'job-123',
          status: statusTerminal,
        } satisfies EventoEstado)
        await instanciaAtual().concluir()

        // Sem o fix, isso reabriria indefinidamente. Avança bem além de qualquer backoff possível.
        await vi.advanceTimersByTimeAsync(60000)

        expect(StreamSimulado.instances).toHaveLength(1)
      },
    )

    it('continua reconectando normalmente após um estado não-terminal seguido de erro', async () => {
      const handlers = novosHandlers()
      abrirAcompanhamentoJob('job-123', handlers)
      await instanciaAtual().abrir()

      await instanciaAtual().emitir('estado', {
        job_id: 'job-123',
        status: 'simulando',
      } satisfies EventoEstado)
      await instanciaAtual().errar()

      await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1)

      expect(StreamSimulado.instances).toHaveLength(2)
    })

    it('não emite reconectando quando o fechamento é o desfecho esperado do estado terminal', async () => {
      const handlers = novosHandlers()
      abrirAcompanhamentoJob('job-123', handlers)
      await instanciaAtual().abrir()

      await instanciaAtual().emitir('estado', {
        job_id: 'job-123',
        status: 'liberado',
      } satisfies EventoEstado)
      await instanciaAtual().errar()

      expect(handlers.onStatusConexao).not.toHaveBeenCalledWith('reconectando')
    })
  })
})
