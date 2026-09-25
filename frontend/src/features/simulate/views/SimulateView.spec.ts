import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import SimulateView from './SimulateView.vue'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { usarStoreJobAtual } from '@/stores/currentJob'
import type { Job } from '@/types/api'

vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<(id: string, signal?: AbortSignal) => Promise<Job>>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>().mockResolvedValue({
      itens: [], pagina: 0, tamanho: 100, total: 0,
    }),
  },
}))

const consultarJob = vi.mocked(apiClient.consultarJob)

function criarRouterDeTeste() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/jobs/:id',
        name: 'simulate',
        component: SimulateView,
      },
      {
        path: '/jobs/:id/finalizar',
        name: 'finalizar',
        component: { template: '<div />' },
      },
      {
        path: '/nova-regra',
        name: 'nova-regra',
        component: { template: '<div />' },
      },
    ],
  })
}

function criarJob(): Job {
  return {
    id: 'job-1',
    status: 'aguardando_decisao_usuario',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    regras: [
      {
        id: 'regra-1',
        versao: 1,
        origem: 'confirmacao_usuario',
        criada_em: '2025-11-24T14:03:00Z',
        representacao: {
          nucleo: {
            vigencia: {
              inicio: '2025-11',
              fim: '2025-11',
            },
            loja: ['Loja 1'],
            marca: ['Marca 1'],
            cargo: ['Cargo 1'],
            percentual: 0.1,
          },
          especificacoes: [],
        },
      },
    ],
    simulacao: {
      id: 'simulacao-1',
      criado_em: '2025-11-24T14:04:47Z',
      status: 'sucesso',
      veredito: 'viavel',
      flag_baixa_rastreabilidade: false,
      resultado: {
        totais: {
          baseline: 480312,
          simulado: 492100,
          diferenca_abs: 11788,
          diferenca_pct: 0.0245,
          orcamento: 485000,
        },
        assercoes: [],
        decomposicao: {},
      },
    },
  }
}

async function montarProcessamento(status: Job['status'] = 'simulando') {
  const job = { ...criarJob(), status, simulacao: null }
  consultarJob.mockResolvedValue(job)
  const router = criarRouterDeTeste()
  const pinia = createPinia()
  await router.push('/jobs/job-1')
  const wrapper = mount(SimulateView, {
    global: {
      plugins: [router, pinia],
      stubs: { FontAwesomeIcon: true },
    },
  })
  await flushPromises()
  return { wrapper, job, store: usarStoreJobAtual(pinia) }
}

describe('SimulateView', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it.each([
    ['aguardando_transcricao', 403],
    ['aguardando_transcricao', 500],
    ['gerando_regra', 403],
    ['gerando_regra', 500],
    ['simulando', 403],
    ['simulando', 500],
  ] as const)('exibe o erro de consulta durante %s quando a API responde %i', async (status, codigo) => {
    const { wrapper, store } = await montarProcessamento(status)
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)

    consultarJob.mockRejectedValueOnce(new HttpError(codigo, 'Não foi possível consultar o processamento.'))
    await store.consultarJob()
    await flushPromises()

    expect(store.job?.status).toBe(status)
    expect(wrapper.get('main h2').text()).toBe('Não foi possível carregar a simulação')
    expect(wrapper.text()).toContain('Não foi possível consultar o processamento.')
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('retoma o progresso e mostra o resultado após recuperar uma consulta com falha', async () => {
    const { wrapper, job, store } = await montarProcessamento()
    consultarJob.mockRejectedValueOnce(new HttpError(500, 'Não foi possível consultar o processamento.'))
    await store.consultarJob()
    await flushPromises()
    expect(wrapper.get('main h2').text()).toBe('Não foi possível carregar a simulação')

    consultarJob.mockResolvedValue(job)
    await store.consultarJob()
    await flushPromises()
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Não foi possível carregar a simulação')

    consultarJob.mockResolvedValue(criarJob())
    await store.consultarJob()
    await flushPromises()
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    wrapper.unmount()
  })

  it('renderiza a tela de simulação', async () => {
    const job = criarJob()
    consultarJob.mockResolvedValue(job)

    const router = criarRouterDeTeste()

    await router.push('/jobs/job-1')
    await router.isReady()

    const wrapper = mount(SimulateView, {
      global: {
        plugins: [router, createPinia()],
      },
    })

    await vi.waitFor(() => {
      expect(wrapper.find('#loja').element).toHaveProperty('value', 'Loja 1')
    })

    expect(wrapper.text()).toContain('Simulação')
    expect(wrapper.text()).toContain('Regra estruturada')
    expect(wrapper.text()).toContain('Dados da simulação')

    expect(wrapper.find('#vigencia').element).toHaveProperty('value', '11/2025')
    expect(wrapper.find('#loja').element).toHaveProperty('value', 'Loja 1')
    expect(wrapper.find('#marca').element).toHaveProperty('value', 'Marca 1')
    expect(wrapper.find('#cargo').element).toHaveProperty('value', 'Cargo 1')
    expect(wrapper.find('#meta').element).toHaveProperty('value', 'R$ 485.000,00')
    expect(wrapper.find('#percentual').element).toHaveProperty('value', '10%')
    expect(wrapper.find('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')

    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    expect(wrapper.text()).toContain('Seguir para Finalização')

    expect(consultarJob).toHaveBeenCalledWith('job-1')
  })
})
