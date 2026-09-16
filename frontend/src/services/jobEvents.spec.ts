import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { abrirAcompanhamentoJob } from './jobEvents'
import { apiClient } from './api'
import type { Job, EventoEtapa, EventoEstado, EventoResultado } from '@/types/api'

vi.mock('./api', () => ({
  apiClient: {
    acompanharJob: vi.fn<(id: string) => string>((id) => `/api/jobs/${id}/events`),
    consultarJob: vi.fn<(id: string) => Promise<Job>>(() =>
      Promise.resolve({
        id: 'job-123',
        status: 'simulando',
        origem: 'formulario',
        competencias: [],
        orcamento: 0,
        criado_em: new Date().toISOString(),
      }),
    ),
  },
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []

  url: string
  listeners = new Map<string, Set<(event: MessageEvent) => void>>()
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  fechada = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(evento: string, handler: (event: MessageEvent) => void) {
    if (!this.listeners.has(evento)) {
      this.listeners.set(evento, new Set())
    }
    this.listeners.get(evento)!.add(handler)
  }

  emitir(evento: string, dados: unknown) {
    const mensagem = new MessageEvent(evento, { data: JSON.stringify(dados) })
    this.listeners.get(evento)?.forEach((handler) => handler(mensagem))
  }

  emitirBruto(evento: string, dataCru: string) {
    const mensagem = new MessageEvent(evento, { data: dataCru })
    this.listeners.get(evento)?.forEach((handler) => handler(mensagem))
  }

  abrir() {
    this.onopen?.()
  }

  errar() {
    this.onerror?.()
  }

  close() {
    this.fechada = true
  }
}

function novosHandlers() {
  return {
    onStatusConexao: vi.fn<(status: 'conectando' | 'aberta' | 'reconectando') => void>(),
    onEstado: vi.fn<(evento: EventoEstado) => void>(),
    onEtapa: vi.fn<(evento: EventoEtapa) => void>(),
    onResultado: vi.fn<(evento: EventoResultado) => void>(),
    onReconciliar: vi.fn<(job: Job) => void>(),
  }
}

function jobFake(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-123',
    status: 'simulando',
    origem: 'formulario',
    competencias: [],
    orcamento: 0,
    criado_em: new Date().toISOString(),
    ...overrides,
  }
}

describe('jobEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  function instanciaAtual(): FakeEventSource {
    const instancia = FakeEventSource.instances[FakeEventSource.instances.length - 1]
    if (!instancia) throw new Error('Nenhuma instância de EventSource foi criada')
    return instancia
  }

  it('abre o stream com a URL de apiClient.acompanharJob', () => {
    abrirAcompanhamentoJob('job-123', novosHandlers())

    expect(apiClient.acompanharJob).toHaveBeenCalledWith('job-123')
    expect(instanciaAtual().url).toBe('/api/jobs/job-123/events')
  })

  it('sinaliza conectando na primeira abertura, sem reconciliar', () => {
    const handlers = novosHandlers()

    abrirAcompanhamentoJob('job-123', handlers)

    expect(handlers.onStatusConexao).toHaveBeenCalledWith('conectando')
    expect(apiClient.consultarJob).not.toHaveBeenCalled()
  })

  it('sinaliza aberta quando a conexão nativa abre', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    instanciaAtual().abrir()

    expect(handlers.onStatusConexao).toHaveBeenLastCalledWith('aberta')
  })

  it('despacha o evento estado desserializado para o handler', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoEstado = { job_id: 'job-123', status: 'simulando', status_anterior: 'gerando_regra' }
    instanciaAtual().emitir('estado', evento)

    expect(handlers.onEstado).toHaveBeenCalledWith(evento)
  })

  it('despacha o evento etapa desserializado para o handler', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoEtapa = { job_id: 'job-123', etapa: 'geracao_codigo', status: 'iniciada' }
    instanciaAtual().emitir('etapa', evento)

    expect(handlers.onEtapa).toHaveBeenCalledWith(evento)
  })

  it('despacha o evento resultado desserializado para o handler', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoResultado = {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
      veredito: 'viavel',
    }
    instanciaAtual().emitir('resultado', evento)

    expect(handlers.onResultado).toHaveBeenCalledWith(evento)
  })

  it('deduplica resultado repetido com o mesmo simulacao_id', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    const evento: EventoResultado = {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
      veredito: 'viavel',
    }

    instanciaAtual().emitir('resultado', evento)
    instanciaAtual().emitir('resultado', evento)

    expect(handlers.onResultado).toHaveBeenCalledTimes(1)
  })

  it('não deduplica resultados de simulacoes distintas', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    instanciaAtual().emitir('resultado', {
      job_id: 'job-123',
      simulacao_id: 'sim-1',
      status: 'sucesso',
    } satisfies EventoResultado)
    instanciaAtual().emitir('resultado', {
      job_id: 'job-123',
      simulacao_id: 'sim-2',
      status: 'sucesso',
    } satisfies EventoResultado)

    expect(handlers.onResultado).toHaveBeenCalledTimes(2)
  })

  it('ignora evento com data que não é JSON válido, sem lançar e sem chamar o handler', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    expect(() => instanciaAtual().emitirBruto('estado', 'não é JSON')).not.toThrow()
    expect(handlers.onEstado).not.toHaveBeenCalled()
  })

  it('ao cair a conexão, fecha a instância nativa e sinaliza reconectando imediatamente', () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)
    instanciaAtual().abrir()

    const instanciaCaida = instanciaAtual()
    instanciaCaida.errar()

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
    instanciaAtual().abrir()
    instanciaAtual().errar()

    expect(FakeEventSource.instances).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_1)
    expect(FakeEventSource.instances).toHaveLength(1)

    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1 - ANTES_DO_MINIMO_TENTATIVA_1)
    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it('cresce o delay exponencialmente em erros consecutivos sem sucesso entre eles', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    // 1º erro (antes de qualquer onopen): delay base ~1000ms
    instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_1)
    expect(FakeEventSource.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1 - ANTES_DO_MINIMO_TENTATIVA_1)
    expect(FakeEventSource.instances).toHaveLength(2)

    // 2º erro consecutivo, sem onopen no meio: delay deve dobrar para ~2000ms
    instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(ANTES_DO_MINIMO_TENTATIVA_2)
    expect(FakeEventSource.instances).toHaveLength(2)
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_2 - ANTES_DO_MINIMO_TENTATIVA_2)
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it('reseta o backoff para o valor base após uma reconexão bem-sucedida', async () => {
    const handlers = novosHandlers()
    abrirAcompanhamentoJob('job-123', handlers)

    // 1º erro, reconecta após o delay base
    instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1)
    expect(FakeEventSource.instances).toHaveLength(2)

    // A nova conexão abre com sucesso, resetando o backoff
    instanciaAtual().abrir()
    instanciaAtual().errar()

    // Se o backoff não tivesse resetado, o delay teria dobrado (mínimo ~2000ms) e não
    // dispararia ainda em 1500ms; reconectar aqui prova que voltou ao delay base (~1000-1200ms).
    await vi.advanceTimersByTimeAsync(1500)
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it('reconecta e chama consultarJob (reconciliação) a partir da segunda abertura', async () => {
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFake())
    const handlers = novosHandlers()

    abrirAcompanhamentoJob('job-123', handlers)
    expect(apiClient.consultarJob).not.toHaveBeenCalled()

    instanciaAtual().abrir()
    instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(1250)

    expect(FakeEventSource.instances).toHaveLength(2)
    expect(apiClient.consultarJob).toHaveBeenCalledWith('job-123')
  })

  it('repassa o job retornado pela reconciliação ao handler onReconciliar', async () => {
    const jobReconciliado = jobFake({ status: 'gerando_regra' })
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobReconciliado)
    const handlers = novosHandlers()

    abrirAcompanhamentoJob('job-123', handlers)
    instanciaAtual().abrir()
    instanciaAtual().errar()
    await vi.advanceTimersByTimeAsync(1250)
    await vi.waitFor(() => expect(handlers.onReconciliar).toHaveBeenCalledWith(jobReconciliado))
  })

  it('fechar() encerra a conexão nativa e cancela o timer de reconexão pendente', async () => {
    const handlers = novosHandlers()
    const { fechar } = abrirAcompanhamentoJob('job-123', handlers)
    instanciaAtual().abrir()
    instanciaAtual().errar()

    fechar()

    expect(instanciaAtual().fechada).toBe(true)

    await vi.advanceTimersByTimeAsync(5000)
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  describe('encerramento pelo servidor em estado terminal', () => {
    it.each(['liberado', 'cancelado', 'arquivado', 'erro'] as const)(
      'não reconecta depois do evento estado com status terminal %s seguido do fechamento do servidor',
      async (statusTerminal) => {
        const handlers = novosHandlers()
        abrirAcompanhamentoJob('job-123', handlers)
        instanciaAtual().abrir()

        // Fotografia final: o contrato diz que o servidor manda o estado terminal e fecha.
        instanciaAtual().emitir('estado', {
          job_id: 'job-123',
          status: statusTerminal,
        } satisfies EventoEstado)
        instanciaAtual().errar()

        // Sem o fix, isso reabriria indefinidamente. Avança bem além de qualquer backoff possível.
        await vi.advanceTimersByTimeAsync(60000)

        expect(FakeEventSource.instances).toHaveLength(1)
      },
    )

    it('continua reconectando normalmente após um estado não-terminal seguido de erro', async () => {
      const handlers = novosHandlers()
      abrirAcompanhamentoJob('job-123', handlers)
      instanciaAtual().abrir()

      instanciaAtual().emitir('estado', {
        job_id: 'job-123',
        status: 'simulando',
      } satisfies EventoEstado)
      instanciaAtual().errar()

      await vi.advanceTimersByTimeAsync(DEPOIS_DO_MAXIMO_TENTATIVA_1)

      expect(FakeEventSource.instances).toHaveLength(2)
    })

    it('não emite reconectando quando o fechamento é o desfecho esperado do estado terminal', () => {
      const handlers = novosHandlers()
      abrirAcompanhamentoJob('job-123', handlers)
      instanciaAtual().abrir()

      instanciaAtual().emitir('estado', {
        job_id: 'job-123',
        status: 'liberado',
      } satisfies EventoEstado)
      instanciaAtual().errar()

      expect(handlers.onStatusConexao).not.toHaveBeenCalledWith('reconectando')
    })
  })
})
