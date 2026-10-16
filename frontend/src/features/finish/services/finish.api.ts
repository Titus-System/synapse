import { http } from '@/services/http'
import type { DetalhamentoSimulacao } from '@/types/api'

export function consultarDetalhamento(jobId: string, simulacaoId: string, signal?: AbortSignal) {
  return http.get<DetalhamentoSimulacao>(
    `/jobs/${encodeURIComponent(jobId)}/simulacoes/${encodeURIComponent(simulacaoId)}/linhas`,
    signal,
  )
}
