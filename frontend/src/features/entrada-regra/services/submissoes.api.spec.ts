import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: async () => 'token-teste',
  iniciarLogin: vi.fn<() => void>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
import { enviarAudio, enviarTexto } from './submissoes.api'
afterEach(() => vi.restoreAllMocks())
it('envia JSON autenticado sem parâmetros obsoletos', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
  await enviarTexto('regra', new AbortController().signal)
  const [url, init] = fetch.mock.calls[0]!
  expect(url).toMatch(/\/submissoes$/)
  expect(JSON.parse(init!.body as string)).toEqual({
    finalidade: 'entrada_inicial',
    tipo: 'texto',
    texto: 'regra',
  })
  expect(new Headers(init!.headers).get('Authorization')).toBe('Bearer token-teste')
})
it('envia as partes multipart sem fixar o boundary do navegador', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
  await enviarAudio(
    new Blob(['audio'], { type: 'audio/webm;codecs=opus' }),
    new AbortController().signal,
  )
  const init = fetch.mock.calls[0]![1]!
  expect(new Headers(init.headers).has('Content-Type')).toBe(false)
  expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-teste')
  const form = init.body as FormData
  expect(form.get('audio')).toBeInstanceOf(Blob)
  expect((form.get('audio') as Blob).type).toBe('audio/webm;codecs=opus')
  expect((form.get('parametros') as Blob).type).toBe('application/json')
})
