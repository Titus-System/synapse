import { http } from '@/services/http'
import type {
  FiltroEventos,
  FiltrosEventosAuditoria,
  PaginaEventosAuditoria,
  PaginaJobsAuditoria,
  RegistroAuditoria,
} from '../types'
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
  listarEventos(filtro: FiltroEventos, pagina: number, tamanho: number, signal?: AbortSignal) {
    const parametros = new URLSearchParams({ pagina: String(pagina), tamanho: String(tamanho) })
    for (const [campo, valor] of Object.entries(filtro)) if (valor) parametros.set(campo, valor)
    return http.get<PaginaEventosAuditoria>('/auditoria/eventos?' + parametros, signal)
  },
  consultarFiltros(signal?: AbortSignal) {
    return http.get<FiltrosEventosAuditoria>('/auditoria/eventos/filtros', signal)
  },
  obterAudio(jobId: string, entradaId: string, signal?: AbortSignal) {
    return http.binario(
      '/auditoria/jobs/' +
        encodeURIComponent(jobId) +
        '/entradas/' +
        encodeURIComponent(entradaId) +
        '/audio',
      signal,
    )
  },
}
