import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { jobFixture, regraFixture, respostaPendente } from '@/services/job.fixtures'
import FinishView from './FinishView.vue'

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    executarAcao: vi.fn<typeof apiClient.executarAcao>(),
  },
}))
vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture())
})
afterEach(() => {
  vi.useRealTimers()
})

async function montar() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id/finalizar', component: FinishView },
      { path: '/nova-regra', component: { template: '<div />' } },
    ],
  })
  await router.push('/jobs/job-1/finalizar')
  const wrapper = mount(FinishView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { TheSidebar: true },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('FinishView', () => {
  it('indica Salvar como etapa atual enquanto aguarda a decisão do usuário', async () => {
    const { wrapper } = await montar()
    expect(wrapper.get('header [aria-current="step"]').text()).toBe('Salvar')
    wrapper.unmount()
  })

  it('mostra a versão mais recente da resposta real de consulta', async () => {
    vi.mocked(apiClient.consultarJob).mockResolvedValue(
      jobFixture({ regras: [{ ...regraFixture(2), id: 'recente-2' }, regraFixture(1)] }),
    )
    const { wrapper } = await montar()
    expect(wrapper.get('h1').text()).toBe('Finalizar Regra')
    expect(wrapper.get('h2').text()).toBe('Regra recent')
    expect(wrapper.text()).toContain('13')
    expect(wrapper.text()).toContain('482.000')
    wrapper.unmount()
  })

  it.each(['salvar', 'arquivar'] as const)(
    'persiste %s antes de navegar e bloqueia cliques repetidos',
    async (acao) => {
      const { wrapper, router } = await montar()
      const resposta = respostaPendente<Awaited<ReturnType<typeof apiClient.executarAcao>>>()
      vi.mocked(apiClient.executarAcao).mockReturnValue(resposta.promise)
      const botao = wrapper.findAll('button').find((item) => item.text().toLowerCase() === acao)!
      await botao.trigger('click')
      await botao.trigger('click')
      expect(apiClient.executarAcao).toHaveBeenCalledExactlyOnceWith('job-1', { acao })
      expect(router.currentRoute.value.path).toBe('/jobs/job-1/finalizar')
      resposta.resolve(jobFixture({ status: acao === 'salvar' ? 'liberado' : 'arquivado' }))
      await flushPromises()
      expect(wrapper.text()).toContain('com sucesso!')
      expect(botao.attributes('disabled')).toBeDefined()
      wrapper.unmount()
    },
  )

  it('reconcilia um conflito sem anunciar sucesso', async () => {
    const { wrapper, router } = await montar()
    vi.mocked(apiClient.executarAcao).mockRejectedValue(new HttpError(409, 'Ação indisponível.'))
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ status: 'arquivado' }))
    await wrapper
      .findAll('button')
      .find((item) => item.text() === 'Salvar')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Ação indisponível.')
    expect(wrapper.text()).not.toContain('com sucesso!')
    expect(apiClient.consultarJob).toHaveBeenCalledTimes(2)
    expect(router.currentRoute.value.path).toBe('/jobs/job-1/finalizar')
    wrapper.unmount()
  })
})
