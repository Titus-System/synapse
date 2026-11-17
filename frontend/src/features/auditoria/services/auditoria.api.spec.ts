import { expect, it, vi } from 'vitest'
import { http } from '@/services/http'
import { auditoriaApi } from './auditoria.api'
vi.mock('@/services/http', () => ({ http: { get: vi.fn<typeof http.get>() } }))
it('pagina apenas a listagem global', async () => {
  const signal = new AbortController().signal
  await auditoriaApi.listar(2, 12, signal)
  expect(http.get).toHaveBeenCalledWith('/auditoria/jobs?pagina=2&tamanho=12', signal)
})
it('codifica o id no detalhe', async () => {
  await auditoriaApi.obter('id/teste')
  expect(http.get).toHaveBeenCalledWith('/auditoria/jobs/id%2Fteste', undefined)
})
it('envia só os filtros preenchidos à lista de eventos', async () => {
  const signal = new AbortController().signal
  await auditoriaApi.listarEventos(
    { usuario: 'rh.outro', mes: '2026-11', loja: '', regra: 'Comissão de novembro' },
    1,
    12,
    signal,
  )
  expect(http.get).toHaveBeenCalledWith(
    '/auditoria/eventos?pagina=1&tamanho=12&usuario=rh.outro&mes=2026-11&regra=Comiss%C3%A3o+de+novembro',
    signal,
  )
})
it('consulta as opções dos filtros', async () => {
  await auditoriaApi.consultarFiltros()
  expect(http.get).toHaveBeenCalledWith('/auditoria/eventos/filtros', undefined)
})
