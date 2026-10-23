import { observarConsulta } from '@/observability/consultasLogging'
import { http } from '@/services/http'
import type { DetalhamentoSimulacao } from '@/types/api'

export function consultarDetalhamento(
  jobId: string,
  simulacaoId: string,
  signal?: AbortSignal,
  resultadoAnteriorId?: string,
) {
  return observarConsulta(
    'consultar_detalhamento',
    jobId,
    () =>
      http.get<DetalhamentoSimulacao>(
        `/jobs/${encodeURIComponent(jobId)}/simulacoes/${encodeURIComponent(simulacaoId)}/linhas${resultadoAnteriorId ? `?resultado_anterior_id=${encodeURIComponent(resultadoAnteriorId)}` : ''}`,
        signal,
      ),
    signal,
  )
}
