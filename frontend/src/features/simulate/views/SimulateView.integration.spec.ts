import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { jobFixture, regraFixture } from '@/services/job.fixtures'
import type { Job } from '@/types/api'
import SimulateView from './SimulateView.vue'

class Stream extends EventTarget {
  static atual: Stream
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  fechado = false
  constructor(readonly url: string) {
    super()
    Stream.atual = this
  }
  close() {
    this.fechado = true
  }
  emitir(tipo: string, dados: unknown) {
    this.dispatchEvent(new MessageEvent(tipo, { data: JSON.stringify(dados) }))
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function montar(consultar: () => Job) {
  vi.stubGlobal('EventSource', Stream)
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(
      async () =>
        new Response(JSON.stringify(consultar()), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id', name: 'simulacao', component: SimulateView },
      { path: '/jobs/:id/finalizar', name: 'finalizar', component: { template: '<div />' } },
      { path: '/nova-regra', component: { template: '<div />' } },
    ],
  })
  await router.push('/jobs/job-1')
  const wrapper = mount(SimulateView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { TheSidebar: true, TheProcessHeader: true, FontAwesomeIcon: true },
    },
  })
  await flushPromises()
  return { wrapper, router, fetchMock }
}

describe('integração da tela com HTTP e SSE', () => {
  it('consome regras[] e atualiza o resultado sem recarregar a página', async () => {
    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['Loja mais recente']
    let resposta = jobFixture({ status: 'gerando_regra', regras: [recente, regraFixture()] })
    const { wrapper, fetchMock } = await montar(() => resposta)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/jobs/job-1')
    expect(Stream.atual.url).toBe('/api/jobs/job-1/events')
    expect(wrapper.get('#loja').element).toHaveProperty('value', 'Loja mais recente')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', '')

    resposta = { ...resposta, status: 'aguardando_decisao_usuario' }
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    Stream.atual.emitir('resultado', {
      job_id: 'job-1',
      simulacao_id: 'simulacao-1',
      status: 'sucesso',
      veredito: 'viavel',
    })
    await flushPromises()
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 482.000,00')
    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    wrapper.unmount()
    expect(Stream.atual.fechado).toBe(true)
  })

  it('habilita as ações quando o job aguarda a decisão sobre a sugestão', async () => {
    const sugestao = regraFixture(2, 'sugestao_adaptacao')
    const resposta = jobFixture({ status: 'aguardando_confirmacao_parametros', regras: [regraFixture(), sugestao] })
    const { wrapper } = await montar(() => resposta)

    const botoes = wrapper.findAll('button')
    expect(botoes.find((botao) => botao.text().includes('SIM!'))?.attributes('disabled')).toBeUndefined()
    expect(botoes.find((botao) => botao.text().includes('Não.'))?.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('preenche os controles existentes com a sugestão recebida pela API', async () => {
    const sugestao = regraFixture(2, 'sugestao_adaptacao')
    const resposta = jobFixture({
      status: 'aguardando_confirmacao_parametros',
      regras: [regraFixture(), sugestao],
    })
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Deseja escolher essa nova regra?')
    const camposLoja = wrapper.findAll('input[id="loja"]')
    expect(camposLoja).toHaveLength(2)
    expect(camposLoja[1]!.element).toHaveProperty('value', '13')
    expect(
      wrapper
        .findAll('button')
        .find((item) => item.text().includes('SIM!'))!
        .attributes('disabled'),
    ).toBeUndefined()
    wrapper.unmount()
  })
})
