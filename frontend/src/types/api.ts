export type CodigoErro =
  | 'requisicao_invalida'
  | 'nao_autenticado'
  | 'sem_permissao'
  | 'job_nao_encontrado'
  | 'estado_invalido'
  | 'simulacao_inviavel'
  | 'nucleo_incompleto'
  | 'regra_incoerente'

export interface ElementoErro {
  ref: string
  motivo: string
}

export interface ApiError {
  codigo: CodigoErro
  mensagem: string
  elementos?: ElementoErro[]
}

export type StatusJob =
  | 'aguardando_transcricao'
  | 'aguardando_confirmacao_parametros'
  | 'gerando_regra'
  | 'simulando'
  | 'simulacao_inviavel'
  | 'aguardando_decisao_usuario'
  | 'liberado'
  | 'cancelado'
  | 'arquivado'
  | 'erro'

export type OrigemJob = 'formulario' | 'voz' | 'reprocessamento'
export type AcaoJob = 'confirmar_liberar' | 'cancelar' | 'salvar' | 'arquivar'
export type Veredito = 'viavel' | 'inviavel' | 'indeterminado'
export type StatusResultado = 'sucesso' | 'assercao_violada' | 'erro_codigo' | 'erro_infra'

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

export interface ExecutarAcaoRequisicao {
  acao: AcaoJob
}

export interface ReprocessarRequisicao {
  competencias?: string[]
  orcamento?: number
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

export interface RegraVersionada {
  id: string
  versao: number
  origem: 'confirmacao_usuario' | 'sugestao_adaptacao' | 'reprocessamento'
  representacao: RepresentacaoRegra
  criada_em: string
}

export interface Simulacao {
  id: string
  criado_em: string
  status: StatusResultado
  flag_baixa_rastreabilidade: boolean
  veredito?: Veredito
  resultado?: ResultadoSimulacao
}

export interface Job {
  id: string
  status: StatusJob
  origem: OrigemJob
  competencias: string[]
  orcamento: number
  criado_em: string
  iniciado_em?: string
  finalizado_em?: string
  job_origem_id?: string
  submissao_id?: string
  motivo?: string
  regra?: RegraVersionada
  simulacao?: Simulacao
}

export interface JobResumo {
  id: string
  status: StatusJob
  competencias: string[]
  orcamento: number
  criado_em: string
  veredito?: Veredito
  finalizado_em?: string
  job_origem_id?: string
}

export interface PaginaJobs {
  itens: JobResumo[]
  pagina: number
  tamanho: number
  total: number
}

export interface ListarJobsParametros {
  pagina?: number
  tamanho?: number
}
