import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { apiClient } from '@/services/api'
import EntradaRegraView from './EntradaRegraView.vue'
import * as submissoes from '../services/submissoes.api'
import rotasEntrada from '../routes'

afterEach(() => vi.restoreAllMocks())

async function abrir() {
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [...rotasEntrada, { path: '/jobs/:id', component: { template: '<div />' } }],
  })
  await router.push('/nova-regra')
  expect(router.currentRoute.value.name).toBe('nova-regra')
  const wrapper = mount(EntradaRegraView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

describe('entrada da regra', () => {
  it('alterna texto e voz sem gravar ou enviar e conserva o texto apenas na tela', async () => {
    vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
      itens: [],
      total: 0,
      pagina: 0,
      tamanho: 100,
    })
    const wrapper = await abrir()
    expect(wrapper.get('[aria-label="Iniciar gravação"]').attributes('disabled')).toBeUndefined()
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
    ).toBeUndefined()
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

it('envia texto e abre o acompanhamento sem registrar o conteúdo', async () => {
  vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
    itens: [],
    total: 0,
    pagina: 0,
    tamanho: 100,
  })
  const envio = vi
    .spyOn(submissoes, 'enviarTexto')
    .mockResolvedValue({ id: 'sub-1', job: { id: 'job-1', status: 'gerando_regra' } })
  const wrapper = await abrir()
  await wrapper.get('button[aria-pressed="false"]').trigger('click')
  await wrapper.get('textarea').setValue('conteudo confidencial')
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Enviar')!
    .trigger('click')
  await flushPromises()
  expect(envio).toHaveBeenCalledWith('conteudo confidencial', expect.any(AbortSignal))
  expect(wrapper.vm.$router.currentRoute.value.path).toBe('/jobs/job-1')
  expect(JSON.stringify(vi.mocked(console.info).mock.calls)).not.toContain('conteudo confidencial')
  expect(
    vi.mocked(console.info).mock.calls.some(([linha]) => JSON.parse(linha).job_id === 'job-1'),
  ).toBe(true)
  wrapper.unmount()
})

it('preserva o texto quando o envio falha e permite tentar novamente', async () => {
  vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
    itens: [],
    total: 0,
    pagina: 0,
    tamanho: 100,
  })
  vi.spyOn(submissoes, 'enviarTexto').mockRejectedValue(new Error('segredo'))
  const wrapper = await abrir()
  await wrapper.get('button[aria-pressed="false"]').trigger('click')
  await wrapper.get('textarea').setValue('minha regra')
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Enviar')!
    .trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível')
  expect(wrapper.get('textarea').element.value).toBe('minha regra')
  expect(JSON.stringify(vi.mocked(console.error).mock.calls)).not.toContain('segredo')
  wrapper.unmount()
})

it('envia áudio uma vez enquanto aguarda e abre o job de transcrição', async () => {
  vi.spyOn(apiClient, 'listarJobs').mockResolvedValue({
    itens: [],
    total: 0,
    pagina: 0,
    tamanho: 100,
  })
  let concluir!: (value: {
    id: string
    job: { id: string; status: 'aguardando_transcricao' }
  }) => void
  const envio = vi.spyOn(submissoes, 'enviarAudio').mockImplementation(
    () =>
      new Promise((resolve) => {
        concluir = resolve
      }),
  )
  const wrapper = await abrir()
  const audio = new Blob(['gravacao'], { type: 'audio/ogg' })
  const entrada = wrapper.findComponent({ name: 'EntradaVoz' })
  entrada.vm.$emit('enviar', audio)
  entrada.vm.$emit('enviar', audio)
  await flushPromises()
  expect(envio).toHaveBeenCalledTimes(1)
  expect(envio).toHaveBeenCalledWith(audio, expect.any(AbortSignal))
  concluir({ id: 'sub-voz', job: { id: 'job-voz', status: 'aguardando_transcricao' } })
  await flushPromises()
  expect(wrapper.vm.$router.currentRoute.value.path).toBe('/jobs/job-voz')
  wrapper.unmount()
})
