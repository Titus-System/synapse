/** Envelope paginado de listagem. Ajustar ao formato efetivo do backend. */
export interface Paginated<T> {
  items: T[]
  page: number
  pageSize: number
  total: number
}

/** Corpo de erro retornado pela API. Ajustar ao formato efetivo do backend. */
export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface Vigencia {
  inicio: string
  fim: string
}

export interface NucleoSubmissao {
  vigencia: Vigencia | null
  loja: string[]
  marca: string[]
  cargo: string[]
  percentual: number | null
}

export interface ConteudoSubmissao {
  nucleo: NucleoSubmissao
  texto_livre: string | null
}

export interface NucleoRegra {
  vigencia?: Vigencia
  loja?: string[]
  marca?: string[]
  cargo?: string[]
  percentual?: number
}

export interface EspecificacaoRegra {
  ref: string
  construto: string
  [campo: string]: unknown
}

export interface RepresentacaoRegra {
  nucleo: NucleoRegra
  especificacoes: EspecificacaoRegra[]
}

export interface CriarJobRequisicao {
  origem: 'formulario'
  orcamento: number
  conteudo: ConteudoSubmissao
  competencias?: string[]
}

export interface ConfirmarParametrosRequisicao {
  regra: RepresentacaoRegra
  orcamento?: number
  competencias?: string[]
}

export interface TotaisSimulacao {
  baseline: number
  simulado: number
  diferenca_abs: number
  diferenca_pct: number
  orcamento: number
}

export interface ResultadoAssercao {
  nome: string
  resultado: string
  detalhe: string | null
}

export interface ResultadoSimulacao {
  totais: TotaisSimulacao
  assercoes: ResultadoAssercao[]
  decomposicao: Record<string, Record<string, number>>
}
