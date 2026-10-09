import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import CorrecaoRegraView from './CorrecaoRegraView.vue'

afterEach(() => vi.restoreAllMocks())

describe('visual do chatbot', () => {
  it('mostra a conversa de exemplo e o processo com envio desabilitado', async () => {
    vi.spyOn(console, 'info').mockImplementation(() => undefined)
    vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
      itens: [],
      total: 0,
      pagina: 0,
      tamanho: 100,
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/jobs/:id/correcao', component: CorrecaoRegraView }],
    })
    await router.push('/jobs/exemplo/correcao')
    const wrapper = mount(CorrecaoRegraView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Refine sua Regra')
    expect(wrapper.find('[aria-label="Etapas do processo"]').exists()).toBe(true)
    expect(wrapper.find('[role="status"]').text()).toContain('Exemplo de conversa')
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button[aria-label="Enviar correção"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('carrega todas as paginas e monta links e contadores do historico', async () => {
    const log = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    const listar = vi
      .spyOn(apiClient, 'listarJobs')
      .mockResolvedValueOnce({
        itens: [
          {
            id: 'regra-a',
            status: 'liberado',
            competencias: [],
            criado_em: '2026-10-08T12:00:00Z',
          },
        ],
        total: 2,
        pagina: 0,
        tamanho: 100,
      })
      .mockResolvedValueOnce({
        itens: [
          {
            id: 'regra-b',
            status: 'arquivado',
            competencias: [],
            criado_em: '2026-10-07T12:00:00Z',
          },
        ],
        total: 2,
        pagina: 1,
        tamanho: 100,
      })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/correcao', component: CorrecaoRegraView }],
    })
    await router.push('/correcao')
    const wrapper = mount(CorrecaoRegraView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(listar).toHaveBeenCalledTimes(2)
    expect(wrapper.get('a[href="/jobs/regra-a"]').text()).toContain('08/10/2026')
    expect(wrapper.get('a[href="/jobs/regra-b"]').text()).toContain('07/10/2026')
    expect(wrapper.get('a[href="/salvas"]').text()).toContain('1')
    expect(wrapper.get('a[href="/arquivadas"]').text()).toContain('1')
    const registro = JSON.parse(log.mock.calls[0]![0])
    expect(registro.extra).toMatchObject({ operacao: 'listar_regras', resultado: 'sucesso' })
    expect(registro.extra.duracao_ms).toBeGreaterThanOrEqual(0)
    expect(log.mock.calls[0]![0]).not.toContain('regra-a')
    wrapper.unmount()
  })
  it('permite tentar de novo sem mostrar o erro interno ou um historico vazio', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.spyOn(console, 'info').mockImplementation(() => undefined)
    vi.spyOn(apiClient, 'listarJobs')
      .mockRejectedValueOnce(new Error('conteudo confidencial'))
      .mockResolvedValueOnce({ itens: [], total: 0, pagina: 0, tamanho: 100 })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/correcao', component: CorrecaoRegraView }],
    })
    await router.push('/correcao')
    const wrapper = mount(CorrecaoRegraView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Nenhuma regra criada ainda')
    expect(wrapper.text()).not.toContain('conteudo confidencial')
    expect(JSON.parse(log.mock.calls[0]![0]).extra.resultado).toBe('falha')
    expect(log.mock.calls[0]![0]).not.toContain('conteudo confidencial')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Nenhuma regra criada ainda')
    wrapper.unmount()
  })
})
