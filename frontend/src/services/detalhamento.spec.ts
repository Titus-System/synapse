import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: async () => 'token-teste',
  iniciarLogin: vi.fn<() => void>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
import { consultarDetalhamento } from './detalhamento'

afterEach(() => vi.restoreAllMocks())

it('consulta o artefato inteiro com autenticação e identificadores escapados', async () => {
  const resposta = { simulacao_id: 'simulacao', linhas: {} }
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(JSON.stringify(resposta)))
  const signal = new AbortController().signal
  expect(await consultarDetalhamento('job/1', 'simulacao/2', signal)).toEqual(resposta)
  const [url, init] = fetch.mock.calls[0]!
  expect(url).toMatch(/\/jobs\/job%2F1\/simulacoes\/simulacao%2F2\/linhas$/)
  expect(init?.signal).toBe(signal)
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer token-teste')
})

it('preserva a ausência de detalhamento nas simulações anteriores', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"simulacao_id":"antiga"}'))
  expect(await consultarDetalhamento('job', 'antiga')).toEqual({ simulacao_id: 'antiga' })
})

it('traduz a recusa sem expor o corpo ou a mensagem interna da API', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        codigo: 'simulacao_nao_encontrada',
        mensagem: 'detalhe interno confidencial',
      }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    ),
  )
  await expect(consultarDetalhamento('job', 'ausente')).rejects.toThrow(
    'Não foi possível encontrar a simulação solicitada.',
  )
})
