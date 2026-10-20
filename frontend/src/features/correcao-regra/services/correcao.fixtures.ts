import type { Job } from '@/types/api'
import type { CorrecaoCriada, Rodada } from '../types'

// Exemplo correcaoPorVozEmTranscricao de GET /jobs/{id}/rodadas no OpenAPI.
export const rodadaVoz: Rodada = {
  id: '5a1c2e3f-4b6d-4e7a-9c8b-0d1e2f3a4b51',
  rodada_anterior_id: null,
  regra_analisada_id: '9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f',
  conflitos: [{ elementos: ['nucleo.percentual'], motivo: 'percentual ausente' }],
  correcao: { tipo: 'voz', texto: null, enviada_em: '2025-11-24T14:03:05Z' },
  regra_resultante_id: null,
  estado: 'em_transcricao',
  criada_em: '2025-11-24T14:02:40Z',
}
export const pendente: Rodada = { ...rodadaVoz, estado: 'pendente', correcao: null }
export const jobCorrecao: Job = {
  id: '3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021',
  status: 'aguardando_confirmacao_parametros',
  origem: 'texto',
  competencias: ['2025-11'],
  criado_em: '2025-11-24T14:00:00Z',
  regras: [],
}
export const vozCriada: CorrecaoCriada = {
  id: '8c3e4a5b-6d8f-4a9c-9eab-2f3a4b5c6d73',
  tipo: 'voz',
  finalidade: 'correcao',
  criado_em: '2025-11-24T14:03:05Z',
  job: { id: jobCorrecao.id, status: jobCorrecao.status },
  rodada: rodadaVoz,
}
