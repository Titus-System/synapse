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
