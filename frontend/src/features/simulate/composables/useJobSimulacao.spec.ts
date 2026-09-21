import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import type { Job } from '@/types/api'
import { HttpError } from '@/services/http'
import { useJobSimulacao } from './useJobSimulacao'

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<(id: string, signal?: AbortSignal) => Promise<Job>>(),
  },
}))

const consultarJob = vi.mocked(apiClient.consultarJob)

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

describe('useJobSimulacao', () => {
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
    const erro = new HttpError(
      404,
      'Não foi possível encontrar o processamento solicitado.',
      {
        code: 'job_nao_encontrado',
      },
    )

    consultarJob.mockRejectedValue(erro)

    const simulacao = useJobSimulacao('job-1')

    await simulacao.iniciar()

    expect(simulacao.job.value).toBeNull()
    expect(simulacao.carregando.value).toBe(false)
    expect(simulacao.erro.value).toBe(
      'Não foi possível encontrar o processamento solicitado.',
    )
    expect(simulacao.erroStatus.value).toBe(404)
    expect(simulacao.erroCodigo.value).toBe('job_nao_encontrado')
    expect(simulacao.erroEspecifico.value).toBe(true)
  })
})