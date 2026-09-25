import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { reactive } from 'vue'
import { apiClient } from '@/services/api'
import { jobFixture } from '@/services/job.fixtures'
import FormularioRegraView from './FormularioRegraView.vue'

const { rota } = vi.hoisted(() => ({
  rota: { atual: { query: {} as Record<string, string> } },
}))

vi.mock('@/services/api', () => ({
  apiClient: {
    criarJob: vi.fn<() => Promise<unknown>>(),
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    listarJobs: vi.fn<() => Promise<unknown>>().mockResolvedValue({
      itens: [
        {
          id: 'job-1',
          status: 'aguardando_confirmacao_parametros',
          competencias: ['2025-09'],
          orcamento: 485000,
          criado_em: '2026-09-17T12:00:00Z',
        },
        {
          id: 'job-2',
          status: 'arquivado',
          competencias: ['2025-09'],
          orcamento: 485000,
          criado_em: '2026-09-16T12:00:00Z',
        },
      ],
      pagina: 0,
      tamanho: 100,
      total: 2,
    }),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => rota.atual,
  useRouter: () => ({
    push: vi.fn<(destino: string) => Promise<void>>(),
    resolve: vi.fn<(destino: string) => { name: string }>(),
  }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  // O formulário observa a query da rota, então ela precisa ser reativa aqui.
  rota.atual = reactive({ query: {} as Record<string, string> })
})

function valorDoCampo(conteiner: VueWrapper, seletor: string): string {
  return (conteiner.get(seletor).element as HTMLInputElement | HTMLSelectElement).value
}

const opcoesDeMontagem = {
  global: {
    plugins: [createPinia()],
    stubs: {
      RouterLink: {
        props: ['to'],
        template: '<a :href="to"><slot /></a>',
      },
    },
  },
}

describe('FormularioRegraView', () => {
  it('preenche os campos com a regra do job indicado e mantém o orçamento em branco', async () => {
    rota.atual.query = { reprocessar: 'job-9' }
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ id: 'job-9' }))

    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)
    await flushPromises()

    expect(apiClient.consultarJob).toHaveBeenCalledWith('job-9')
    expect(valorDoCampo(conteiner, '#vigencia-inicio')).toBe('2025-11')
    expect(valorDoCampo(conteiner, '#vigencia-fim')).toBe('2025-11')
    expect(valorDoCampo(conteiner, '#loja')).toBe('13')
    expect(valorDoCampo(conteiner, '#marca')).toBe('10')
    expect(valorDoCampo(conteiner, '#cargo')).toBe('100')
    expect(valorDoCampo(conteiner, '#percentual')).toBe('2,5')
    expect(valorDoCampo(conteiner, '#orcamento')).toBe('')
    expect(conteiner.get('[role="status"]').text()).toContain('Informe o novo orçamento')
  })

  it('esvazia o formulário ao sair do reprocessamento pelo menu', async () => {
    rota.atual.query = { reprocessar: 'job-9' }
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ id: 'job-9' }))

    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)
    await flushPromises()
    expect(valorDoCampo(conteiner, '#loja')).toBe('13')

    rota.atual.query = {}
    await flushPromises()

    expect(valorDoCampo(conteiner, '#loja')).toBe('')
    expect(valorDoCampo(conteiner, '#vigencia-inicio')).toBe('')
    expect(conteiner.find('[role="status"]').exists()).toBe(false)
  })

  it('não consulta job algum quando a rota não pede reprocessamento', async () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)
    await flushPromises()

    expect(apiClient.consultarJob).not.toHaveBeenCalled()
    expect(valorDoCampo(conteiner, '#loja')).toBe('')
  })

  it('mantém somente o título e a descrição no cabeçalho do formulário', () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)
    const cabecalho = conteiner.get('#formulario-regra > header')

    expect(conteiner.get('.tela-de-negocio').classes()).toContain('tela-de-negocio')
    expect(cabecalho.get('h1').text()).toBe('Capture uma Regra de Negócio')
    expect(cabecalho.findAll('p')).toHaveLength(1)
    expect(cabecalho.get('p').text()).toContain('Escreva os parâmetros da regra.')
  })

  it('carrega as regras recentes pela API', async () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)

    await vi.waitFor(() => {
      expect(conteiner.text()).toContain('Regra · 17/09/2026')
      expect(conteiner.text()).toContain('Salvas1')
      expect(conteiner.text()).toContain('Arquivadas1')
    })
  })

  it('mostra a pendência no próprio campo ao tentar enviar dados vazios', async () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)

    await conteiner.get('form').trigger('submit')

    expect(conteiner.get('#loja-erro').text()).toBe('Informe ao menos um código de loja.')
    expect(conteiner.get('#loja').attributes('aria-invalid')).toBe('true')
  })
})
