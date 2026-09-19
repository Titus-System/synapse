import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import type {
  EventoEtapa,
  Job,
} from '@/types/api'
import { useJobSimulacao } from './useJobSimulacao'

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn(),
    acompanharJob: vi.fn(),
  },
}))

class FakeEventSource {
  static instances: FakeEventSource[] = []

  readonly url: string
  readonly listeners = new Map<string, (evento: MessageEvent) => void>()
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(
    tipo: string,
    listener: (evento: MessageEvent) => void,
  ): void {
    this.listeners.set(tipo, listener)
  }

  close(): void {
    this.closed = true
  }

  emitir<T>(tipo: string, dados: T): void {
    const listener = this.listeners.get(tipo)

    listener?.(
      new MessageEvent(tipo, {
        data: JSON.stringify(dados),
      }),
    )
  }

  emitirErro(): void {
    this.onerror?.()
  }
}

vi.stubGlobal('EventSource', FakeEventSource)

const consultarJob = vi.mocked(apiClient.consultarJob)
const acompanharJob = vi.mocked(apiClient.acompanharJob)

function criarJobParcial(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    status: 'gerando_regra',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    ...overrides,
  }
}

function obterUltimoStream(): FakeEventSource {
  const stream = FakeEventSource.instances[FakeEventSource.instances.length - 1]

  if (!stream) {
    throw new Error('Nenhum EventSource foi criado.')
  }

  return stream
}

describe('useJobSimulacao', () => {
  afterEach(() => {
    vi.clearAllMocks()
    FakeEventSource.instances.length = 0
  })

  it('abre o stream de eventos usando o id do job', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const simulacao = useJobSimulacao('job-1')

    await simulacao.iniciar()

    expect(acompanharJob).toHaveBeenCalledWith('job-1')
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0]?.url).toBe(
      'http://localhost:8080/jobs/job-1/events',
    )
  })

  it('busca o job quando o estado recebido aguarda confirmação dos parâmetros', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const job = criarJobParcial({
      status: 'aguardando_confirmacao_parametros',
      regra: {
        id: 'regra-1',
        versao: 1,
        origem: 'confirmacao_usuario',
        representacao: {
          nucleo: {
            vigencia: {
              inicio: '2025-11',
              fim: '2025-11',
            },
            loja: ['13'],
            marca: ['10'],
            cargo: ['100'],
            percentual: 0.025,
          },
          especificacoes: [],
        },
        criada_em: '2025-11-24T14:02:00Z',
      },
    })

    consultarJob.mockResolvedValue(job)

    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()

    const stream = obterUltimoStream()

    stream.emitir('estado', {
      job_id: 'job-1',
      status: 'aguardando_confirmacao_parametros',
    })

    await vi.waitFor(() => {
      expect(consultarJob).toHaveBeenCalledWith('job-1')
    })

    expect(simulacao.job.value).toEqual(job)
    expect(simulacao.aguardandoConfirmacao.value).toBe(true)
    expect(simulacao.carregando.value).toBe(false)
  })

  it('guarda a última etapa recebida pelo stream', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()

    const stream = obterUltimoStream()

    const etapa: EventoEtapa = {
      job_id: 'job-1',
      etapa: 'geracao_codigo',
      status: 'iniciada',
    }

    stream.emitir('etapa', etapa)

    expect(simulacao.etapaAtual.value).toEqual(etapa)
  })

  it('busca o job quando recebe o evento resultado', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const job = criarJobParcial({
      status: 'simulacao_inviavel',
      simulacao: {
        id: 'simulacao-1',
        criado_em: '2025-11-24T14:04:47Z',
        status: 'sucesso',
        veredito: 'inviavel',
        flag_baixa_rastreabilidade: false,
        resultado: {
          totais: {
            baseline: 480312,
            simulado: 492100,
            diferenca_abs: 11788,
            diferenca_pct: 0.0245,
            orcamento: 485000,
          },
          assercoes: [],
          decomposicao: {},
        },
      },
    })

    consultarJob.mockResolvedValue(job)

    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()

    const stream = obterUltimoStream()

    stream.emitir('resultado', {
      job_id: 'job-1',
      simulacao_id: 'simulacao-1',
      status: 'sucesso',
      veredito: 'inviavel',
    })

    await vi.waitFor(() => {
      expect(consultarJob).toHaveBeenCalledWith('job-1')
    })

    expect(simulacao.job.value).toEqual(job)
    expect(simulacao.simulacaoInviavel.value).toBe(true)
    expect(simulacao.resultadoDisponivel.value).toBe(true)
    expect(simulacao.carregando.value).toBe(false)
  })

  it('consulta o job ao receber um estado terminal', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const job = criarJobParcial({
      status: 'liberado',
    })

    consultarJob.mockResolvedValue(job)

    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()

    const stream = obterUltimoStream()

    stream.emitir('estado', {
      job_id: 'job-1',
      status: 'liberado',
      status_anterior: 'aguardando_decisao_usuario',
    })

    await vi.waitFor(() => {
      expect(consultarJob).toHaveBeenCalledWith('job-1')
    })

    expect(simulacao.job.value).toEqual(job)
    expect(simulacao.carregando.value).toBe(false)
    expect(stream.closed).toBe(true)
  })

  it('reabre o stream quando a conexão cai', async () => {
    acompanharJob.mockReturnValue('http://localhost:8080/jobs/job-1/events')

    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()

    const primeiroStream = obterUltimoStream()

    primeiroStream.emitirErro()

    expect(primeiroStream.closed).toBe(true)

    await vi.waitFor(
      () => {
        expect(FakeEventSource.instances).toHaveLength(2)
      },
      { timeout: 1500 },
    )

    expect(acompanharJob).toHaveBeenCalledTimes(1)
    expect(FakeEventSource.instances[1]?.url).toBe(
      'http://localhost:8080/jobs/job-1/events',
    )
  })
})