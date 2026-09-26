import { afterEach, describe, expect, it, vi } from 'vitest'

const adaptadorKeycloak = vi.hoisted(() => ({
  iniciarLogin: vi.fn<() => Promise<void>>().mockResolvedValue(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
  obterTokenDeAcesso: vi.fn<() => Promise<string | undefined>>(),
}))

vi.mock('./keycloak', () => adaptadorKeycloak)

import { http } from './http'

afterEach(() => {
	vi.restoreAllMocks()
	adaptadorKeycloak.obterTokenDeAcesso.mockReset().mockResolvedValue(undefined)
	adaptadorKeycloak.limparTokenDoKeycloak.mockReset()
	adaptadorKeycloak.iniciarLogin.mockClear()
})

describe('http', () => {
	it('anexa o token de autenticação à chamada', async () => {
		adaptadorKeycloak.obterTokenDeAcesso.mockResolvedValue('token-de-teste')
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
		expect(headers.get('Authorization')).toBe('Bearer token-de-teste')
	})

	it('limpa o token e reinicia o login ao receber 401', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 401 }))

		await Promise.all([
      expect(http.get('/jobs')).rejects.toMatchObject({ status: 401 }),
      expect(http.stream('/api/jobs/job-1/events', new AbortController().signal)).rejects.toMatchObject({ status: 401 }),
    ])

		expect(adaptadorKeycloak.limparTokenDoKeycloak).toHaveBeenCalledTimes(2)
		await vi.waitFor(() => expect(adaptadorKeycloak.iniciarLogin).toHaveBeenCalledOnce())
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


describe('transporte autenticado', () => {
  it('aguarda o token renovado antes de enviar o formulário', async () => {
    let concluirRenovacao!: (valor: string | undefined) => void
    const renovacao = new Promise<string | undefined>((resolve) => { concluirRenovacao = resolve })
    adaptadorKeycloak.obterTokenDeAcesso.mockReturnValue(renovacao)
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))

    const resposta = http.post('/jobs', { origem: 'formulario' })
    expect(fetchMock).not.toHaveBeenCalled()
    concluirRenovacao('token-renovado')
    await resposta

    const init = fetchMock.mock.calls[0]?.[1]
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer token-renovado')
    expect(init?.body).toBe(JSON.stringify({ origem: 'formulario' }))
    expect(adaptadorKeycloak.iniciarLogin).not.toHaveBeenCalled()
  })

  it('envia Bearer também no SSE e obtém o token atual a cada abertura', async () => {
    adaptadorKeycloak.obterTokenDeAcesso.mockResolvedValueOnce('token-1').mockResolvedValueOnce('token-2')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(': heartbeat\n\n', {
      headers: { 'content-type': 'text/event-stream;charset=UTF-8' },
    }))
    const controle = new AbortController()

    await (await http.stream('/api/jobs/job-1/events', controle.signal)).cancel()
    await (await http.stream('/api/jobs/job-1/events', controle.signal)).cancel()

    expect(fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get('Authorization')))
      .toEqual(['Bearer token-1', 'Bearer token-2'])
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/jobs/job-1/events')
    expect(init?.signal).toBe(controle.signal)
    expect(new Headers(init?.headers).get('Accept')).toBe('text/event-stream')
  })

  it('não envia requisição nem descarta sessão em uma falha transitória da renovação', async () => {
    adaptadorKeycloak.obterTokenDeAcesso.mockRejectedValue(new Error('Falha de rede'))
    const fetchMock = vi.spyOn(globalThis, 'fetch')

    await expect(http.post('/jobs', {})).rejects.toMatchObject({
      status: 0,
      message: 'Não foi possível renovar sua sessão. Tente novamente.',
    })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(adaptadorKeycloak.limparTokenDoKeycloak).not.toHaveBeenCalled()
    expect(adaptadorKeycloak.iniciarLogin).not.toHaveBeenCalled()
  })

  it('não abre o SSE quando a tela é fechada durante a renovação', async () => {
    let concluirRenovacao!: (valor: string | undefined) => void
    const renovacao = new Promise<string | undefined>((resolve) => { concluirRenovacao = resolve })
    adaptadorKeycloak.obterTokenDeAcesso.mockReturnValue(renovacao)
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    const controle = new AbortController()
    const stream = http.stream('/api/jobs/job-1/events', controle.signal)

    controle.abort()
    concluirRenovacao('token-renovado')

    await expect(stream).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejeita uma resposta que não seja um stream SSE', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>Login</html>', {
      headers: { 'content-type': 'text/html' },
    }))

    await expect(http.stream('/api/jobs/job-1/events', new AbortController().signal))
      .rejects.toMatchObject({ status: 0 })
  })
})
