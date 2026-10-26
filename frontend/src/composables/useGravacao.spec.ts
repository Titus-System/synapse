import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useGravacao } from './useGravacao'

class Gravador {
  static isTypeSupported = () => true
  static tamanho = 8
  static ultimo: Gravador
  state = 'inactive'
  ondataavailable?: (event: { data: Blob }) => void
  onstop?: () => void
  onerror?: () => void
  constructor() {
    Gravador.ultimo = this
  }
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([new Uint8Array(Gravador.tamanho)]) })
    this.onstop?.()
  }
}
const wrappers: ReturnType<typeof mount>[] = []
const stop = vi.fn<() => void>()
beforeEach(() => {
  Gravador.tamanho = 8
  vi.useFakeTimers()
  vi.spyOn(console, 'info').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: vi
        .fn<() => Promise<unknown>>()
        .mockResolvedValue({ getTracks: () => [{ stop }] }),
    },
  })
  URL.createObjectURL = vi.fn<() => string>(() => 'blob:teste')
  URL.revokeObjectURL = vi.fn<() => void>()
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  vi.useRealTimers()
})
function montar() {
  let gravacao!: ReturnType<typeof useGravacao>
  wrappers.push(
    mount({
      setup() {
        gravacao = useGravacao(() => 'job-a')
        return () => null
      },
    }),
  )
  return gravacao
}
it.each([
  ['NotAllowedError', 'permissao_negada', 'Permissão'],
  ['NotFoundError', 'sem_microfone', 'Nenhum microfone'],
])(
  'trata %s com código fechado, correlação e sem exceção bruta',
  async (nome, codigo, mensagem) => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(
      new DOMException('conteudo privado', nome),
    )
    const gravacao = montar()
    await gravacao.iniciar()
    expect(gravacao.erro.value).toContain(mensagem)
    const log = JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0]))
    expect(log).toMatchObject({
      job_id: 'job-a',
      'service.name': 'synapse-frontend',
      extra: { operacao: 'gravar_audio', codigo, resultado: 'falha' },
    })
    expect(JSON.stringify(log)).not.toContain('conteudo privado')
    expect(log.extra.duracao_ms).toBeGreaterThanOrEqual(0)
  },
)
it('sem suporte mantém alternativa de texto e registra causa', async () => {
  vi.stubGlobal('MediaRecorder', undefined)
  const gravacao = montar()
  await gravacao.iniciar()
  expect(gravacao.erro.value).toContain('texto')
  expect(JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0])).extra.codigo).toBe(
    'sem_suporte',
  )
})
it.each([
  [0, 'audio_vazio'],
  [5 * 1024 * 1024 + 1, 'audio_muito_grande'],
])('recusa %s bytes e libera o microfone', async (bytes, codigo) => {
  Gravador.tamanho = Number(bytes)
  const gravacao = montar()
  await gravacao.iniciar()
  gravacao.parar()
  expect(gravacao.audio.value).toBeNull()
  expect(stop).toHaveBeenCalledOnce()
  expect(JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0])).extra.codigo).toBe(codigo)
})
it('erro do gravador libera recursos sem publicar áudio parcial', async () => {
  const gravacao = montar()
  await gravacao.iniciar()
  Gravador.ultimo.onerror?.()
  expect(gravacao.audio.value).toBeNull()
  expect(stop).toHaveBeenCalledOnce()
  expect(JSON.parse(String(vi.mocked(console.error).mock.calls[0]![0])).extra.codigo).toBe(
    'falha_gravacao',
  )
})
it('descarte durante permissão pendente não permite captura tardia', async () => {
  let conceder!: (value: MediaStream) => void
  vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
    new Promise((resolve) => {
      conceder = resolve
    }),
  )
  const gravacao = montar()
  const iniciando = gravacao.iniciar()
  gravacao.descartar()
  conceder({ getTracks: () => [{ stop }] } as unknown as MediaStream)
  await iniciando
  expect(gravacao.gravando.value).toBe(false)
  expect(gravacao.audio.value).toBeNull()
  expect(stop).toHaveBeenCalledOnce()
  expect(JSON.parse(String(vi.mocked(console.info).mock.calls[0]![0])).extra.codigo).toBe(
    'cancelado',
  )
})
it('não recria URL com evento onstop atrasado após descartar', async () => {
  const gravacao = montar()
  await gravacao.iniciar()
  const callback = Gravador.ultimo.onstop!
  gravacao.descartar()
  callback()
  expect(URL.createObjectURL).not.toHaveBeenCalled()
  expect(gravacao.audio.value).toBeNull()
})
