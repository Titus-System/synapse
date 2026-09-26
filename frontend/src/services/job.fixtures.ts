import type { Job, JobCriado, RegraVersionada } from '@/types/api'

export function regraFixture(
  versao = 1,
  origem: RegraVersionada['origem'] = 'confirmacao_usuario',
): RegraVersionada {
  return {
    id: `regra-${versao}`,
    versao,
    origem,
    criada_em: '2025-11-24T14:03:00Z',
    representacao: {
      nucleo: {
        vigencia: { inicio: '2025-11', fim: '2025-11' },
        loja: ['13'],
        marca: ['10'],
        cargo: ['100'],
        percentual: 0.025,
      },
      especificacoes: [],
    },
  }
}

export function jobFixture(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    status: 'aguardando_decisao_usuario',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    regras: [regraFixture()],
    simulacao: {
      id: 'simulacao-1',
      criado_em: '2025-11-24T14:04:47Z',
      status: 'sucesso',
      veredito: 'viavel',
      flag_baixa_rastreabilidade: false,
      resultado: {
        totais: {
          baseline: 480000,
          simulado: 482000,
          diferenca_abs: 2000,
          diferenca_pct: 0.0041666667,
          orcamento: 485000,
        },
        assercoes: [],
        decomposicao: {
          por_elemento: {},
          por_loja: {},
          por_marca: {},
          por_cargo: {},
          por_competencia: {},
        },
      },
    },
    ...overrides,
  }
}

export function jobCriadoFixture(overrides: Partial<JobCriado> = {}): JobCriado {
  return {
    id: 'job-1',
    status: 'gerando_regra',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    regra: regraFixture(),
    ...overrides,
  }
}

export function respostaPendente<T>() {
  let resolver!: (value: T) => void
  const promise = new Promise<T>((resolve) => {
    resolver = resolve
  })
  return { promise, resolve: (value: T) => resolver(value) }
}


export function jobComSugestaoFixture(overrides: Partial<Job> = {}): Job {
  const original = regraFixture()
  const sugestao = regraFixture(2, 'sugestao_adaptacao')
  sugestao.representacao.nucleo.percentual = 0.0246
  const resultadoOriginal = jobFixture().simulacao!
  resultadoOriginal.regra_id = original.id
  resultadoOriginal.veredito = 'inviavel'
  resultadoOriginal.resultado!.totais!.simulado = 492100
  const resultadoSugestao = jobFixture().simulacao!
  resultadoSugestao.id = 'simulacao-2'
  resultadoSugestao.regra_id = sugestao.id
  resultadoSugestao.resultado!.totais!.simulado = 484226.4
  return jobFixture({
    regras: [sugestao, original],
    simulacoes: [resultadoOriginal, resultadoSugestao],
    simulacao: resultadoSugestao,
    ...overrides,
  })
}
