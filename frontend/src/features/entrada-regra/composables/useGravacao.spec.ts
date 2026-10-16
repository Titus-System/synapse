import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { useGravacao } from './useGravacao'

class Gravador {
  static isTypeSupported = () => true
  state = 'inactive'
  ondataavailable?: (event: { data: Blob }) => void
  onstop?: () => void
  start() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['audio']) })
    this.onstop?.()
  }
}
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
function montar() {
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  let gravacao!: ReturnType<typeof useGravacao>
  const wrapper = mount({
    setup() {
      gravacao = useGravacao()
      return () => null
    },
  })
  return {
    wrapper,
    get gravacao() {
      return gravacao
    },
  }
}
it('para aos 180 segundos, permite prévia e libera microfone e URL', async () => {
  vi.useFakeTimers()
  const stop = vi.fn<() => void>()
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: vi
        .fn<() => Promise<unknown>>()
        .mockResolvedValue({ getTracks: () => [{ stop }] }),
    },
  })
  URL.createObjectURL = vi.fn<() => string>().mockReturnValue('blob:teste')
  URL.revokeObjectURL = vi.fn<() => void>()
  const { wrapper, gravacao } = montar()
  await gravacao.iniciar()
  expect(gravacao.gravando.value).toBe(true)
  vi.advanceTimersByTime(180_000)
  expect(gravacao.gravando.value).toBe(false)
  expect(gravacao.audio.value?.size).toBeGreaterThan(0)
  expect(stop).toHaveBeenCalled()
  wrapper.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:teste')
})
it('libera uma permissão concedida depois de sair da tela', async () => {
  let resolver!: (stream: unknown) => void
  const stop = vi.fn<() => void>()
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: () =>
        new Promise((r) => {
          resolver = r
        }),
    },
  })
  const { wrapper, gravacao } = montar()
  const pedido = gravacao.iniciar()
  wrapper.unmount()
  resolver({ getTracks: () => [{ stop }] })
  await pedido
  expect(stop).toHaveBeenCalledOnce()
  expect(gravacao.audio.value).toBeNull()
})
it('trata permissão negada sem expor a exceção', async () => {
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: vi.fn<() => Promise<unknown>>().mockRejectedValue(new Error('segredo')),
    },
  })
  const { wrapper, gravacao } = montar()
  await gravacao.iniciar()
  await flushPromises()
  expect(gravacao.erro.value).toContain('permissão')
  expect(JSON.stringify(vi.mocked(console.error).mock.calls)).not.toContain('segredo')
  wrapper.unmount()
})
