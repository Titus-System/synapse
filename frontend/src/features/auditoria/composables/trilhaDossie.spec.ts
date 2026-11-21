import { expect, it, vi } from 'vitest'
import { eventoExemplo, paginaEventosExemplo } from '../auditoria.fixture'
import { trilhaCronologica } from './trilhaDossie'
import type { PaginaEventosAuditoria } from '../types'
type ListarPagina = (pagina: number) => Promise<PaginaEventosAuditoria>
it('reúne todas as páginas e devolve do mais antigo para o mais recente', async () => {
  const recente = eventoExemplo({ instante: '2026-11-03T12:05:00Z', origem_id: 'c' })
  const meio = eventoExemplo({ instante: '2026-11-03T12:03:00Z', origem_id: 'b' })
  const antigo = eventoExemplo({ instante: '2026-11-03T12:01:00Z', origem_id: 'a' })
  const listar = vi
    .fn<ListarPagina>()
    .mockResolvedValueOnce(paginaEventosExemplo([recente, meio], { total: 3, tamanho: 2 }))
    .mockResolvedValueOnce(paginaEventosExemplo([antigo], { pagina: 1, total: 3, tamanho: 2 }))
  expect(await trilhaCronologica(listar)).toEqual([antigo, meio, recente])
  expect(listar.mock.calls).toEqual([[0], [1]])
})
it('para numa página vazia mesmo que o total não feche', async () => {
  const listar = vi
    .fn<ListarPagina>()
    .mockResolvedValueOnce(paginaEventosExemplo([eventoExemplo()], { total: 5 }))
    .mockResolvedValueOnce(paginaEventosExemplo([], { pagina: 1, total: 5 }))
  expect(await trilhaCronologica(listar)).toHaveLength(1)
  expect(listar).toHaveBeenCalledTimes(2)
})
