import { afterEach, expect, it, vi } from 'vitest'
vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: async () => 'token-teste',
  iniciarLogin: vi.fn<() => void>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
import { enviarCorrecaoTexto, enviarCorrecaoVoz, listarRodadas } from './correcao.api'
import { HttpError } from '@/services/http'
import { jobCorrecao, rodadaVoz, vozCriada } from './correcao.fixtures'
afterEach(() => vi.restoreAllMocks())
function lerBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const leitor = new FileReader()
    leitor.onload = () => resolve(String(leitor.result))
    leitor.readAsText(blob)
  })
}
it('envia audio e parametros JSON no multipart autenticado, sem fixar boundary', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(JSON.stringify(vozCriada)))
  const signal = new AbortController().signal
  const resposta = await enviarCorrecaoVoz(
    jobCorrecao.id,
    new Blob(['audio privado'], { type: 'audio/webm;codecs=opus' }),
    signal,
  )
  const [url, init] = fetch.mock.calls[0]!
  expect(url).toBe('/api/submissoes')
  expect(init?.method).toBe('POST')
  expect(init?.signal).toBe(signal)
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer token-teste')
  expect(new Headers(init?.headers).has('Content-Type')).toBe(false)
  const form = init?.body as FormData
  expect([...form.keys()]).toEqual(['audio', 'parametros'])
  expect((form.get('audio') as Blob).type).toBe('audio/webm;codecs=opus')
  const parametros = form.get('parametros') as Blob
  expect(parametros.type).toBe('application/json')
  expect(JSON.parse(await lerBlob(parametros))).toEqual({
    finalidade: 'correcao',
    tipo: 'voz',
    job_id: jobCorrecao.id,
  })
  expect(resposta.rodada).toEqual(rodadaVoz)
})
it('envia texto como alternativa e lê a rodada de voz ao recarregar', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(vozCriada)))
    .mockResolvedValueOnce(new Response(JSON.stringify([rodadaVoz])))
  const signal = new AbortController().signal
  await enviarCorrecaoTexto(jobCorrecao.id, 'correcao privada', signal)
  expect(JSON.parse(fetch.mock.calls[0]![1]!.body as string)).toEqual({
    finalidade: 'correcao',
    tipo: 'texto',
    job_id: jobCorrecao.id,
    texto: 'correcao privada',
  })
  expect(await listarRodadas(jobCorrecao.id, signal)).toEqual([rodadaVoz])
  expect(fetch.mock.calls[1]![0]).toBe(`/api/jobs/${jobCorrecao.id}/rodadas`)
})
it.each([400, 409, 413])('preserva falha HTTP %s para tratamento no fluxo', async (status) => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        codigo: status === 409 ? 'estado_invalido' : 'audio_invalido',
        mensagem: 'privado',
      }),
      { status, headers: { 'Content-Type': 'application/json' } },
    ),
  )
  await expect(
    enviarCorrecaoVoz(jobCorrecao.id, new Blob(['audio']), new AbortController().signal),
  ).rejects.toBeInstanceOf(HttpError)
})
