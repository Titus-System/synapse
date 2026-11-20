import type { EventoAuditoria, PaginaEventosAuditoria } from '../types'
/** Todos os eventos do job, página a página, do mais antigo para o mais recente. */
export async function trilhaCronologica(
  listarPagina: (pagina: number) => Promise<PaginaEventosAuditoria>,
): Promise<EventoAuditoria[]> {
  const eventos: EventoAuditoria[] = []
  for (let pagina = 0; ; pagina++) {
    const resposta = await listarPagina(pagina)
    eventos.push(...resposta.itens)
    if (!resposta.itens.length || eventos.length >= resposta.total) break
  }
  // A API ordena do mais recente para o mais antigo; a trilha se lê na ordem em que aconteceu.
  return eventos.reverse()
}
