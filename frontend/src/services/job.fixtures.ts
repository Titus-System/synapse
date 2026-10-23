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

export function jobSemOrcamentoFixture(): Job {
  const job = jobFixture({ orcamento: undefined })
  delete job.simulacao!.veredito
  delete job.simulacao!.resultado!.totais!.orcamento
  return job
}

export function jobComMetaFixture(): Job {
  const job = jobFixture({
    meta_venda: 1000000,
    meta_sugerida: { meta_venda: 1200000, total_simulado: 484500, orcamento: 485000 },
  })
  job.simulacao!.regra_id = job.regras[0]!.id
  job.simulacao!.meta_venda = 1000000
  return job
}

export function jobMetaAceitaFixture(): Job {
  const job = jobComMetaFixture()
  delete job.meta_sugerida
  const original = structuredClone(job.simulacao!)
  job.simulacao!.id = 'simulacao-meta-aceita'
  job.simulacao!.meta_venda = 1200000
  job.simulacao!.resultado!.totais!.simulado = 484500
  job.simulacoes = [original, job.simulacao!]
  return job
}

export function jobBuscandoMetaFixture(): Job & { busca_meta_em_curso: true } {
  const job = jobComMetaFixture()
  delete job.meta_sugerida
  return { ...job, busca_meta_em_curso: true }
}

export function jobComTentativasFixture(status: Job['status'] = 'aguardando_decisao_usuario'): Job {
  const job = jobComSugestaoFixture({ status })
  const tentativa = job.regras.find((regra) => regra.origem === 'sugestao_adaptacao')!
  const final = regraFixture(3, 'sugestao_adaptacao')
  final.representacao.nucleo.percentual = 0.02
  const simulacaoFinal = structuredClone(job.simulacao!)
  simulacaoFinal.id = 'simulacao-3'
  simulacaoFinal.regra_id = final.id
  simulacaoFinal.resultado!.totais!.simulado = 480500
  job.simulacao!.veredito = 'inviavel'
  job.simulacao!.resultado!.totais!.simulado = 490000
  job.regras = [
    final,
    tentativa,
    job.regras.find((regra) => regra.origem !== 'sugestao_adaptacao')!,
  ]
  job.simulacoes!.push(simulacaoFinal)
  job.simulacao = simulacaoFinal
  if (status === 'simulacao_inviavel') simulacaoFinal.veredito = 'inviavel'
  return job
}
