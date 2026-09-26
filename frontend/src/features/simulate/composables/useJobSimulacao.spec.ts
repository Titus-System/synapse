import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import type { Job } from '@/types/api'
import {
  jobFixture,
  jobComSugestaoFixture,
  respostaPendente,
} from '@/services/job.fixtures'
import { HttpError } from '@/services/http'
import { useJobSimulacao } from './useJobSimulacao'

vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<(id: string, signal?: AbortSignal) => Promise<Job>>(),
    confirmarParametros: vi.fn<typeof apiClient.confirmarParametros>(),
    executarAcao: vi.fn<typeof apiClient.executarAcao>(),
  },
}))

const consultarJob = vi.mocked(apiClient.consultarJob)

function criarJobParcial(overrides: Partial<Job> = {}): Job {
  return {
    regras: [],
    id: 'job-1',
    status: 'gerando_regra',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    ...overrides,
  }
}

describe('useJobSimulacao', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('consulta o job ao iniciar a simulação', async () => {
    const job = criarJobParcial()

    consultarJob.mockResolvedValue(job)

    const simulacao = useJobSimulacao('job-1')

    await simulacao.iniciar()

    expect(consultarJob).toHaveBeenCalledWith('job-1')
    expect(simulacao.job.value).toEqual(job)
    expect(simulacao.carregando.value).toBe(false)
    expect(simulacao.erro.value).toBeNull()
  })

  it('identifica uma simulação inviável com o resultado retornado pelo job', async () => {
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

    expect(simulacao.job.value).toEqual(job)
    expect(simulacao.simulacaoInviavel.value).toBe(true)
    expect(simulacao.resultadoDisponivel.value).toBe(true)
    expect(simulacao.carregando.value).toBe(false)
  })

  it('guarda o erro específico retornado pela API', async () => {
    const erro = new HttpError(404, 'Não foi possível encontrar o processamento solicitado.', {
      code: 'job_nao_encontrado',
    })

    consultarJob.mockRejectedValue(erro)

    const simulacao = useJobSimulacao('job-1')

    await simulacao.iniciar()

    expect(simulacao.job.value).toBeNull()
    expect(simulacao.carregando.value).toBe(false)
    expect(simulacao.erro.value).toBe('Não foi possível encontrar o processamento solicitado.')
    expect(simulacao.erroStatus.value).toBe(404)
    expect(simulacao.erroCodigo.value).toBe('job_nao_encontrado')
    expect(simulacao.erroEspecifico.value).toBe(true)
  })
  it('separa a regra original da sugestão e permite finalizar a alternativa já simulada', async () => {
    const job = jobComSugestaoFixture()
    consultarJob.mockResolvedValue(job)
    const tela = useJobSimulacao('job-1')
    await tela.iniciar()
    expect(tela.regra.value?.versao).toBe(1)
    expect(tela.sugestao.value?.versao).toBe(2)
    expect(tela.simulacao.value?.resultado?.totais?.simulado).toBe(492100)
    expect(tela.simulacaoSugestao.value?.resultado?.totais?.simulado).toBe(484226.4)
    expect(tela.podeAceitarSugestao.value).toBe(true)
    expect(apiClient.confirmarParametros).not.toHaveBeenCalled()
  })

  it('mantém o resultado original durante a simulação da sugestão', async () => {
    const job = jobComSugestaoFixture({ status: 'simulando', simulacao: null })
    job.simulacoes = job.simulacoes!.slice(0, 1)
    consultarJob.mockResolvedValue(job)
    const tela = useJobSimulacao('job-1')
    await tela.iniciar()
    expect(tela.simulacao.value?.veredito).toBe('inviavel')
    expect(tela.simulacaoSugestao.value).toBeNull()
    expect(tela.podeAceitarSugestao.value).toBe(false)
  })

  it('não atribui um resultado antigo sem regra_id à sugestão', async () => {
    const job = jobComSugestaoFixture({ simulacoes: undefined })
    delete job.simulacao!.regra_id
    consultarJob.mockResolvedValue(job)
    const tela = useJobSimulacao('job-1')
    await tela.iniciar()
    expect(tela.simulacaoSugestao.value).toBeNull()
    expect(tela.podeAceitarSugestao.value).toBe(false)
  })

  it('aguarda a persistência do cancelamento e impede chamadas duplicadas', async () => {
    consultarJob.mockResolvedValue(jobFixture({ status: 'simulacao_inviavel' }))
    const resposta = respostaPendente<Job>()
    vi.mocked(apiClient.executarAcao).mockReturnValue(resposta.promise)
    const simulacao = useJobSimulacao('job-1')
    await simulacao.iniciar()
    const cancelamento = simulacao.cancelar()
    expect(await simulacao.cancelar()).toBe(false)
    expect(apiClient.executarAcao).toHaveBeenCalledExactlyOnceWith('job-1', { acao: 'cancelar' })
    consultarJob.mockResolvedValue(jobFixture({ status: 'cancelado' }))
    resposta.resolve(jobFixture({ status: 'cancelado' }))
    expect(await cancelamento).toBe(true)
    expect(simulacao.status.value).toBe('cancelado')
  })

  it.each(['inviavel', 'indeterminado'] as const)('não aceita alternativa com veredito %s', async (veredito) => {
    const job = jobComSugestaoFixture()
    job.simulacoes![1]!.veredito = veredito
    consultarJob.mockResolvedValue(job)
    const tela = useJobSimulacao('job-1')
    await tela.iniciar()
    expect(tela.podeAceitarSugestao.value).toBe(false)
  })
})
