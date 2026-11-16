import { http } from '@/services/http'
import type { PaginaJobsAuditoria, RegistroAuditoria } from '../types'
export const auditoriaApi = {
  listar(pagina = 0, tamanho = 12, signal?: AbortSignal) {
    return http.get<PaginaJobsAuditoria>(
      '/auditoria/jobs?' +
        new URLSearchParams({ pagina: String(pagina), tamanho: String(tamanho) }),
      signal,
    )
  },
  obter(id: string, signal?: AbortSignal) {
    return http.get<RegistroAuditoria>('/auditoria/jobs/' + encodeURIComponent(id), signal)
  },
}
