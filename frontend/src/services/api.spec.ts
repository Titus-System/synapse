import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('apiClient', () => {
  it('monta a paginação conforme o contrato', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ itens: [], pagina: 2, tamanho: 10, total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await apiClient.listarJobs({ pagina: 2, tamanho: 10 })

    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/jobs?pagina=2&tamanho=10')
  })

  it('expõe a URL do stream sem abrir conexão SSE', () => {
    expect(apiClient.acompanharJob('job 1')).toBe('/api/jobs/job%201/events')
  })
})
