import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import CorrecaoRegraView from './CorrecaoRegraView.vue'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { pendente, rodadaVoz, jobCorrecao, vozCriada } from '../services/correcao.fixtures'
import type { Rodada } from '../types'
vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: async () => 'token',
  iniciarLogin: vi.fn<() => void>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))
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
    this.ondataavailable?.({ data: new Blob(['audio confidencial']) })
    this.onstop?.()
  }
}
let rodadas: Rodada[]
let posts: RequestInit[]
let falhar = false
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  rodadas = [pendente]
  posts = []
  falhar = false
  vi.spyOn(console, 'info').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.stubGlobal('MediaRecorder', Gravador)
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: vi
        .fn<() => Promise<unknown>>()
        .mockResolvedValue({ getTracks: () => [{ stop: vi.fn<() => void>() }] }),
    },
  })
  URL.createObjectURL = vi.fn<() => string>(() => 'blob:audio')
  URL.revokeObjectURL = vi.fn<() => void>()
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    if (init?.method === 'POST') {
      posts.push(init)
      if (falhar)
        return new Response(
          JSON.stringify({ codigo: 'audio_invalido', mensagem: 'excecao confidencial' }),
          { status: 400, headers: { 'Content-Type': 'application/json' } },
        )
      rodadas = [rodadaVoz]
      return new Response(JSON.stringify(vozCriada))
    }
    return new Response(
      JSON.stringify(
        String(url).endsWith('/rodadas')
          ? rodadas
          : String(url).includes('?')
            ? { itens: [], total: 0, pagina: 0, tamanho: 100 }
            : jobCorrecao,
      ),
    )
  })
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})
async function montar() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id/correcao', component: CorrecaoRegraView },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
  await router.push(`/jobs/${jobCorrecao.id}/correcao`)
  const w = mount(CorrecaoRegraView, { global: { plugins: [createPinia(), router] } })
  wrappers.push(w)
  await flushPromises()
  return w
}
async function gravar(w: ReturnType<typeof mount>) {
  await w.get('[aria-label="Iniciar gravação"]').trigger('click')
  await flushPromises()
  await w.get('[aria-label="Parar gravação"]').trigger('click')
  expect(w.find('audio[controls]').exists()).toBe(true)
  await w
    .findAll('button')
    .find((b) => b.text() === 'Enviar gravação')!
    .trigger('click')
  await flushPromises()
}
function conferirLogs() {
  const schema = JSON.parse(
    readFileSync(
      resolve(
        dirname(fileURLToPath(import.meta.url)),
        '../../../../../contracts/observability/log.schema.json',
      ),
      'utf8',
    ),
  )
  const logs = [...vi.mocked(console.info).mock.calls, ...vi.mocked(console.error).mock.calls].map(
    (call) => JSON.parse(String(call[0])),
  )
  for (const log of logs) {
    for (const campo of schema.required) expect(log).toHaveProperty(campo)
    expect(schema.properties.level.enum).toContain(log.level)
    expect(schema.properties['service.name'].enum).toContain(log['service.name'])
    expect(new Date(log.timestamp).toISOString()).toBe(log.timestamp)
  }
  const correlacionados = logs.filter((log) =>
    ['gravar_audio', 'enviar_correcao_voz', 'ler_rodadas'].includes(log.extra.operacao),
  )
  expect(correlacionados.length).toBeGreaterThan(0)
  for (const log of correlacionados) {
    expect(log.job_id).toBe(jobCorrecao.id)
    expect(log.extra.codigo).toEqual(expect.any(String))
    expect(log.extra.duracao_ms).toBeGreaterThanOrEqual(0)
  }
  expect(JSON.stringify(logs)).not.toMatch(
    /audio confidencial|transcricao confidencial|excecao confidencial|percentual ausente/,
  )
  return logs
}
it('integra gravador, view, composable, HTTP multipart, transcrição e reconciliação', async () => {
  const w = await montar()
  await gravar(w)
  expect(posts).toHaveLength(1)
  expect(posts[0]!.body).toBeInstanceOf(FormData)
  expect(w.get('textarea').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('Seu áudio está sendo transcrito')
  expect(w.find('audio').exists()).toBe(false)
  rodadas = [
    {
      ...rodadaVoz,
      estado: 'em_reextracao',
      correcao: { ...rodadaVoz.correcao!, texto: 'transcricao confidencial' },
    },
  ]
  const handlers = vi.mocked(abrirAcompanhamentoJob).mock.calls[0]![1]
  handlers.onReconciliar()
  handlers.onReconciliar()
  await flushPromises()
  expect(w.text()).toContain('transcricao confidencial')
  expect(w.text()).toContain('Correção por voz')
  expect(w.text()).toContain('Sua correção está sendo interpretada')
  expect(w.findAll('[data-rodada]')).toHaveLength(1)
  const logs = conferirLogs()
  expect(logs).toContainEqual(
    expect.objectContaining({
      extra: expect.objectContaining({ operacao: 'gravar_audio', codigo: 'ok' }),
    }),
  )
  expect(logs).toContainEqual(
    expect.objectContaining({
      extra: expect.objectContaining({ operacao: 'enviar_correcao_voz', codigo: 'ok' }),
    }),
  )
})
it('falha da transcrição libera uma nova tentativa e falha do POST mantém texto disponível', async () => {
  rodadas = [
    { ...rodadaVoz, estado: 'reextracao_falhou' },
    { ...pendente, id: 'sucessora' },
  ]
  falhar = true
  const w = await montar()
  expect(w.text()).toContain('Não foi possível transcrever seu áudio')
  expect(w.get('textarea').attributes('disabled')).toBeUndefined()
  await gravar(w)
  expect(w.text()).toContain('Não foi possível usar o áudio')
  expect(w.get('textarea').attributes('disabled')).toBeUndefined()
  expect(w.text()).not.toContain('excecao confidencial')
  const logs = conferirLogs()
  expect(logs).toContainEqual(
    expect.objectContaining({
      extra: expect.objectContaining({ operacao: 'enviar_correcao_voz', codigo: 'audio_invalido' }),
    }),
  )
})
