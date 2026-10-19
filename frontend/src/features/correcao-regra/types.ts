import type { Conflito, StatusJob } from '@/types/api'

export type EstadoRodada =
  'pendente' | 'em_transcricao' | 'em_reextracao' | 'reextracao_falhou' | 'corrigida' | 'abandonada'
export interface Rodada {
  id: string
  rodada_anterior_id: string | null
  regra_analisada_id: string
  conflitos: Conflito[]
  correcao: { tipo?: 'texto' | 'voz'; texto: string | null; enviada_em: string } | null
  regra_resultante_id: string | null
  estado: EstadoRodada
  criada_em: string
}
export interface CorrecaoCriada {
  id: string
  tipo: 'texto' | 'voz'
  finalidade: 'correcao'
  criado_em: string
  job: { id: string; status: StatusJob }
  rodada: Rodada
}
