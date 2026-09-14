import { afterEach, describe, expect, it, vi } from 'vitest'

import { http } from './http'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('http', () => {
  it('não envia token de autenticação', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'job-1' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await http.get<{ id: string }>('/jobs/job-1')

    const request = fetchMock.mock.calls[0]
    const init = request?.[1]
    const headers = new Headers(init?.headers)
    expect(headers.has('Authorization')).toBe(false)
  })

  it('transforma erro de validação em mensagem com o nome do campo', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          codigo: 'nucleo_incompleto',
          mensagem: 'A regra está incompleta.',
          elementos: [{ ref: 'nucleo.percentual', motivo: 'Campo obrigatório não informado.' }],
        }),
        { status: 422, headers: { 'content-type': 'application/json' } },
      ),
    )

    await expect(http.post('/jobs', {})).rejects.toMatchObject({
      message: 'Percentual de comissionamento: Campo obrigatório não informado.',
      fieldErrors: [
        {
          field: 'Percentual de comissionamento',
          message: 'Campo obrigatório não informado.',
        },
      ],
    })
  })

  it('usa mensagem própria para erro do servidor sem expor o status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('erro interno', { status: 503 }))

    await expect(http.get('/jobs')).rejects.toMatchObject({
      message: 'O serviço está temporariamente indisponível. Tente novamente em alguns instantes.',
    })
  })

  it('não envia body em requisição GET', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ itens: [] }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    await http.get('/jobs')

    const init = fetchMock.mock.calls[0]?.[1]
    expect(init?.method).toBe('GET')
    expect(init).not.toHaveProperty('body')
  })
})
