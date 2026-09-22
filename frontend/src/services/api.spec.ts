import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './api'
import { jobCriadoFixture } from './job.fixtures'

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
  it.each([undefined, { competencias: ['2025-10'], orcamento: 500000 }])(
    'reprocessa pelo contrato preservando o novo ID e a procedência',
    async (parametros) => {
      const novo = jobCriadoFixture({
        id: 'novo-job',
        origem: 'reprocessamento',
        job_origem_id: 'job-original',
      })
      const fetchMock = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValue(
          new Response(JSON.stringify(novo), {
            status: 201,
            headers: { 'content-type': 'application/json' },
          }),
        )
      expect(await apiClient.reprocessarJob('job-original', parametros)).toEqual(novo)
      expect(fetchMock).toHaveBeenCalledOnce()
      expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/jobs/job-original/reprocessar')
      expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(
        parametros ? JSON.stringify(parametros) : undefined,
      )
    },
  )

  it.each([404, 409, 422, 503])(
    'propaga o erro HTTP %i sem retornar um job fictício',
    async (status) => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue(
        new Response(JSON.stringify({ codigo: 'estado_invalido', mensagem: 'detalhe interno' }), {
          status,
          headers: { 'content-type': 'application/json' },
        }),
      )
      await expect(apiClient.reprocessarJob('job-original')).rejects.toMatchObject({ status })
    },
  )
})
