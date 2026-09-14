import { http } from '@/services/http'
import type {
  ConfirmarParametrosRequisicao,
  CriarJobRequisicao,
  ExecutarAcaoRequisicao,
  Job,
  ListarJobsParametros,
  PaginaJobs,
  ReprocessarRequisicao,
} from '@/types/api'

function jobPath(id: string): string {
  return `/jobs/${encodeURIComponent(id)}`
}

export const apiClient = {
  criarJob(requisicao: CriarJobRequisicao, signal?: AbortSignal) {
    return http.post<Job, CriarJobRequisicao>('/jobs', requisicao, signal)
  },

  listarJobs(parametros: ListarJobsParametros = {}, signal?: AbortSignal) {
    const query = new URLSearchParams()
    if (parametros.pagina !== undefined) query.set('pagina', String(parametros.pagina))
    if (parametros.tamanho !== undefined) query.set('tamanho', String(parametros.tamanho))
    const suffix = query.size > 0 ? `?${query.toString()}` : ''

    return http.get<PaginaJobs>(`/jobs${suffix}`, signal)
  },

  consultarJob(id: string, signal?: AbortSignal) {
    return http.get<Job>(jobPath(id), signal)
  },

  acompanharJob(id: string) {
    return http.url(`${jobPath(id)}/events`)
  },

  confirmarParametros(id: string, requisicao: ConfirmarParametrosRequisicao, signal?: AbortSignal) {
    return http.post<Job, ConfirmarParametrosRequisicao>(
      `${jobPath(id)}/parameters`,
      requisicao,
      signal,
    )
  },

  executarAcao(id: string, requisicao: ExecutarAcaoRequisicao, signal?: AbortSignal) {
    return http.post<Job, ExecutarAcaoRequisicao>(`${jobPath(id)}/actions`, requisicao, signal)
  },

  reprocessarJob(id: string, requisicao?: ReprocessarRequisicao, signal?: AbortSignal) {
    return http.post<Job, ReprocessarRequisicao | undefined>(
      `${jobPath(id)}/reprocessar`,
      requisicao,
      signal,
    )
  },
}
