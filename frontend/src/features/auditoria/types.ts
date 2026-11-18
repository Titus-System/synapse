import type {
  AcaoJob,
  Conflito,
  JobResumo,
  RegraVersionada,
  StatusJob,
  StatusResultado,
  Veredito,
} from '@/types/api'
export interface JobAuditoria extends Omit<JobResumo, 'veredito'> {
  origem: 'formulario' | 'texto' | 'voz' | 'reprocessamento'
  usuario: { login: string; nome: string }
  iniciado_em?: string
}
export interface PaginaJobsAuditoria {
  itens: JobAuditoria[]
  pagina: number
  tamanho: number
  total: number
}
export interface EntradaAuditoria {
  id: string
  tipo: 'formulario' | 'texto' | 'voz'
  finalidade: 'entrada_inicial' | 'correcao'
  criado_em: string
  texto?: string
  conteudo?: Record<string, unknown>
  formato?: 'webm' | 'ogg' | 'wav' | 'mp4'
  transcrito_em?: string
}
export type EstadoAudioEntrada = 'carregando' | 'pronto' | 'erro' | 'indisponivel'
export interface AudioEntrada {
  estado: EstadoAudioEntrada
  url?: string
}
/** Áudios pedidos no dossiê, pelo id da entrada; a entrada ausente ainda não foi pedida. */
export type AudiosEntradas = Readonly<Record<string, AudioEntrada>>
export interface VersaoAuditoria extends RegraVersionada {
  hash: string
  regra_origem_id?: string
  tentativa?: number
  parametros?: Record<string, unknown>
}
export interface CodigoAuditoria {
  id: string
  regra_id: string
  linguagem: string
  fonte: string
  prompt_id: string
  criado_em: string
}
export interface RodadaAuditoria {
  id: string
  rodada_anterior_id: string | null
  regra_analisada_id: string
  conflitos: Conflito[]
  correcao: { tipo?: 'texto' | 'voz'; texto: string | null; enviada_em: string } | null
  regra_resultante_id: string | null
  estado: string
  criada_em: string
}
export interface ChamadaModeloAuditoria {
  id: string
  no: string
  modelo: { provedor: string; modelo: string; versao: string; parametros?: Record<string, unknown> }
  prompt: string
  criado_em: string
  resposta?: {
    id: string
    texto: string
    criado_em: string
    consumo_tokens?: { tokens_in: number; tokens_out: number; custo_usd?: number } | null
  }
}
export interface RegistroAuditoria {
  job: JobAuditoria
  entradas: EntradaAuditoria[]
  versoes: VersaoAuditoria[]
  codigos: CodigoAuditoria[]
  etapas: {
    id: string
    no: string
    concluido_em: string
    conclusao: Record<string, unknown>
    regra_id?: string
    submissao_id?: string
    prompt_id?: string
    codigo_gerado_id?: string
  }[]
  rodadas: RodadaAuditoria[]
  chamadas_modelo: ChamadaModeloAuditoria[]
  resultados: Record<string, unknown>[]
  simulacoes: Record<string, unknown>[]
  transicoes: Record<string, unknown>[]
  acoes: Record<string, unknown>[]
  sugestoes_meta: Record<string, unknown>[]
  explicacoes: Record<string, unknown>[]
}
export type AbaDossie = 'regra' | 'conversa' | 'simulacoes'
export type TipoEventoAuditoria =
  | 'entrada'
  | 'rodada_correcao'
  | 'versao_regra'
  | 'codigo_gerado'
  | 'resultado_simulacao'
  | 'sugestao_meta_criada'
  | 'sugestao_meta_aceita'
  | 'acao_usuario'
  | 'job_erro'
export interface EventoAuditoria {
  instante: string
  tipo: TipoEventoAuditoria
  autor: 'usuario' | 'sistema'
  usuario_login: string
  job: { id: string; nome?: string | null; status: StatusJob }
  origem_id: string
  loja?: string | null
  marca?: string | null
  cargo?: string | null
  finalidade?: string | null
  tipo_entrada?: string | null
  origem_versao?: string | null
  versao?: number | null
  status?: StatusResultado | null
  veredito?: Veredito | null
  acao?: AcaoJob | null
}
export interface ContadoresEventosAuditoria {
  eventos: number
  usuarios: number
  regras: number
  simulacoes_com_falha: number
}
export interface PaginaEventosAuditoria {
  itens: EventoAuditoria[]
  pagina: number
  tamanho: number
  total: number
  contadores: ContadoresEventosAuditoria
}
export interface FiltrosEventosAuditoria {
  usuarios: string[]
  meses: string[]
  lojas: string[]
  marcas: string[]
  cargos: string[]
}
export type CampoFiltroEventos = 'usuario' | 'mes' | 'loja' | 'marca' | 'cargo' | 'regra'
/** Parâmetros de `GET /auditoria/eventos`; campo ausente não filtra. */
export type FiltroEventos = Partial<Record<CampoFiltroEventos, string>>
/** O formulário do painel: texto vazio é "todos", e o mês aceita também `todos`. */
export type FiltroPainel = Record<CampoFiltroEventos, string>
