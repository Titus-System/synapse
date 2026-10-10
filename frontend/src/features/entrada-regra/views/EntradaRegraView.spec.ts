import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { apiClient } from '@/services/api'
import EntradaRegraView from './EntradaRegraView.vue'
import rotasEntrada from '../routes'

afterEach(() => vi.restoreAllMocks())

async function abrir() {
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: rotasEntrada,
  })
  await router.push('/nova-regra')
  expect(router.currentRoute.value.name).toBe('nova-regra')
  const wrapper = mount(EntradaRegraView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

describe('previa da entrada da regra', () => {
  it('alterna texto e voz sem gravar ou enviar e conserva o texto apenas na tela', async () => {
    vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
      itens: [],
      total: 0,
      pagina: 0,
      tamanho: 100,
    })
    const wrapper = await abrir()
    expect(wrapper.get('[aria-label="Iniciar gravação"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[aria-current="step"]').text()).toContain('Voz/Texto')
    await wrapper.get('button[aria-pressed="false"]').trigger('click')
    await wrapper.get('textarea').setValue('Uma regra de exemplo')
    expect(wrapper.text()).toContain('20 / 8000')
    expect(wrapper.get('textarea').attributes('maxlength')).toBe('8000')
    expect(
      wrapper
        .findAll('button')
        .find((b) => b.text() === 'Enviar')!
        .attributes('disabled'),
    ).toBeDefined()
    await wrapper.get('button[aria-pressed="false"]').trigger('click')
    await wrapper.get('button[aria-pressed="false"]').trigger('click')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe(
      'Uma regra de exemplo',
    )
    wrapper.unmount()
  })
  it('mostra historico real com links e contadores na barra lateral', async () => {
    vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
      itens: [
        {
          id: 'regra-exemplo',
          status: 'arquivado',
          competencias: [],
          criado_em: '2026-10-09T12:00:00Z',
        },
      ],
      total: 1,
      pagina: 0,
      tamanho: 100,
    })
    const wrapper = await abrir()
    expect(wrapper.get('a[href="/jobs/regra-exemplo"]').text()).toContain('09/10/2026')
    expect(wrapper.get('a[href="/arquivadas"]').text()).toContain('1')
    expect(wrapper.get('a[href="/nova-regra"]').attributes('href')).toBe('/nova-regra')
    wrapper.unmount()
  })
  it('permite recuperar o historico sem expor a mensagem interna', async () => {
    vi.spyOn(apiClient, 'listarJobs')
      .mockRejectedValueOnce(new Error('segredo'))
      .mockResolvedValueOnce({ itens: [], total: 0, pagina: 0, tamanho: 100 })
    const wrapper = await abrir()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('segredo')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Nenhuma regra criada ainda')
    wrapper.unmount()
  })
})
