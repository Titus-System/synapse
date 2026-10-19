import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import EntradaVoz from './EntradaVoz.vue'

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
    this.ondataavailable?.({ data: new Blob(['audio privado']) })
    this.onstop?.()
  }
}
const parar = vi.fn<() => void>()
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.spyOn(console, 'info').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: vi
        .fn<() => Promise<unknown>>()
        .mockResolvedValue({ getTracks: () => [{ stop: parar }] }),
    },
  })
  URL.createObjectURL = vi.fn<() => string>(() => 'blob:gravacao')
  URL.revokeObjectURL = vi.fn<() => void>()
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})
function montar(compacto = false) {
  const w = mount(EntradaVoz, { props: { enviando: false, jobId: 'job-a', compacto } })
  wrappers.push(w)
  return w
}
it('grava, para, ouve, envia só uma vez e libera recursos', async () => {
  const w = montar()
  expect(w.get('[role="status"]').text()).toBe('Clique para iniciar a gravação')
  expect(w.text()).toContain('Grave até 3 minutos (máximo de 5 MB).')
  expect(w.findAll('button').find((b) => b.text() === 'Enviar gravação')).toBeUndefined()
  await w.get('[aria-label="Iniciar gravação"]').trigger('click')
  await flushPromises()
  await w.get('[aria-label="Parar gravação"]').trigger('click')
  expect(parar).toHaveBeenCalledOnce()
  expect(w.get('audio').attributes('controls')).toBeDefined()
  const enviar = w.findAll('button').find((b) => b.text() === 'Enviar gravação')!
  await enviar.trigger('click')
  await w.setProps({ enviando: true })
  await enviar.trigger('click')
  expect(w.emitted('enviar')).toHaveLength(1)
  expect(w.find('audio').exists()).toBe(true)
  await w.setProps({ enviando: false, bloqueada: true })
  expect(w.find('audio').exists()).toBe(false)
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:gravacao')
  expect(JSON.stringify(vi.mocked(console.info).mock.calls)).not.toContain('audio privado')
})
it('descarta gravação ao trocar job e bloqueia a captura durante envio', async () => {
  const w = montar()
  await w.get('[aria-label="Iniciar gravação"]').trigger('click')
  await flushPromises()
  await w.setProps({ jobId: 'job-b' })
  expect(parar).toHaveBeenCalledOnce()
  expect(w.find('audio').exists()).toBe(false)
  await w.setProps({ enviando: true })
  expect(w.get('[aria-label="Iniciar gravação"]').attributes('disabled')).toBeDefined()
})
it('no chatbot, mostra só o microfone enquanto não há gravação', () => {
  const w = montar(true)
  expect(w.get('[aria-label="Iniciar gravação"]').attributes('disabled')).toBeUndefined()
  expect(w.findAll('button')).toHaveLength(1)
  expect(w.find('audio').exists()).toBe(false)
})
