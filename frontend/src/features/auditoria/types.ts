import type { JobResumo, RegraVersionada } from '@/types/api'
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
  }[]
  rodadas: { id: string; regra_resultante_id: string | null; [campo: string]: unknown }[]
  chamadas_modelo: Record<string, unknown>[]
  resultados: Record<string, unknown>[]
  simulacoes: Record<string, unknown>[]
  transicoes: Record<string, unknown>[]
  acoes: Record<string, unknown>[]
  sugestoes_meta: Record<string, unknown>[]
  explicacoes: Record<string, unknown>[]
}
export type AbaDossie = 'regra' | 'conversa' | 'simulacoes'
