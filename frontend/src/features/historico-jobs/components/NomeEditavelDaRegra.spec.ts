import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { Job, JobResumo } from '@/types/api'
import NomeEditavelDaRegra from './NomeEditavelDaRegra.vue'

vi.mock('@/services/api', () => ({
  apiClient: {
    renomearJob: vi.fn<typeof apiClient.renomearJob>(),
  },
}))

const resumo: JobResumo = {
  id: 'job-1',
  status: 'liberado',
  competencias: ['2025-09'],
  criado_em: '2026-09-19T12:00:00Z',
}
const rotuloComData = `Regra · ${new Date(resumo.criado_em).toLocaleDateString('pt-BR')}`
const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  setActivePinia(createPinia())
})
afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  vi.resetAllMocks()
})

function montar(dados: JobResumo = resumo) {
  const wrapper = mount(NomeEditavelDaRegra, {
    props: { resumo: dados },
    attachTo: document.body,
  })
  wrappers.push(wrapper)
  return wrapper
}

async function abrirEdicao(wrapper: ReturnType<typeof montar>) {
  await wrapper.get('button').trigger('click')
  await flushPromises()
  return wrapper.get('input')
}

it('mostra o nome, a data de criação e o botão Editar', () => {
  const wrapper = montar({ ...resumo, nome: 'Comissão de novembro' })

  expect(wrapper.get('h2').text()).toBe('Comissão de novembro')
  expect(wrapper.text()).toContain(
    `Criada em ${new Date(resumo.criado_em).toLocaleDateString('pt-BR')}`,
  )
  expect(wrapper.get('button').text()).toBe('Editar')
  expect(wrapper.find('input').exists()).toBe(false)
})

it('abre o campo com o rótulo atual selecionado e esconde o botão', async () => {
  const wrapper = montar()

  const campo = await abrirEdicao(wrapper)

  expect((campo.element as HTMLInputElement).value).toBe(rotuloComData)
  expect(document.activeElement).toBe(campo.element)
  expect(wrapper.find('h2').exists()).toBe(false)
  expect(wrapper.find('button').exists()).toBe(false)
})

it('cancela com Esc sem chamar a api e volta ao rótulo anterior', async () => {
  const wrapper = montar()
  const campo = await abrirEdicao(wrapper)

  await campo.setValue('Outro nome')
  await campo.trigger('keydown.esc')

  expect(apiClient.renomearJob).not.toHaveBeenCalled()
  expect(wrapper.find('input').exists()).toBe(false)
  expect(wrapper.get('h2').text()).toBe(rotuloComData)
})

it('não envia um nome vazio e mostra a mensagem', async () => {
  const wrapper = montar()
  const campo = await abrirEdicao(wrapper)

  await campo.setValue('   ')
  await campo.trigger('keydown.enter')

  expect(apiClient.renomearJob).not.toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toBe('Informe um nome para a regra.')
})

it('envia o nome digitado com Enter e encerra a edição', async () => {
  vi.mocked(apiClient.renomearJob).mockResolvedValue({ id: 'job-1', nome: 'Comissão' } as Job)
  const wrapper = montar()
  const campo = await abrirEdicao(wrapper)

  await campo.setValue('Comissão')
  await campo.trigger('keydown.enter')
  await flushPromises()

  expect(apiClient.renomearJob).toHaveBeenCalledWith('job-1', { nome: 'Comissão' })
  expect(wrapper.find('input').exists()).toBe(false)
  expect(wrapper.get('h2').text()).toBe('Comissão')
})

it('mantém o campo aberto e mostra a mensagem do código quando a api recusa', async () => {
  vi.mocked(apiClient.renomearJob).mockRejectedValue(
    new HttpError(400, 'O nome informado é inválido.'),
  )
  const wrapper = montar()
  const campo = await abrirEdicao(wrapper)

  await campo.setValue('Comissão')
  await campo.trigger('keydown.enter')
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toBe('O nome informado é inválido.')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Comissão')
})

it('não envia de novo enquanto a requisição está em andamento', async () => {
  let concluir: (job: Job) => void = () => undefined
  vi.mocked(apiClient.renomearJob).mockReturnValue(
    new Promise<Job>((resolver) => {
      concluir = resolver
    }),
  )
  const wrapper = montar()
  const campo = await abrirEdicao(wrapper)

  await campo.setValue('Comissão')
  await campo.trigger('keydown.enter')
  await campo.trigger('keydown.enter')

  expect(apiClient.renomearJob).toHaveBeenCalledTimes(1)
  expect(campo.attributes('disabled')).toBeDefined()
  concluir({ id: 'job-1', nome: 'Comissão' } as Job)
  await flushPromises()
})
