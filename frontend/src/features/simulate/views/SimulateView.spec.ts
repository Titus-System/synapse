import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { mount } from '@vue/test-utils'
import SimulateView from './SimulateView.vue'
import { apiClient } from '@/services/api'
import type { Job } from '@/types/api'

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<(id: string, signal?: AbortSignal) => Promise<Job>>(),
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
    status: 'liberado',
    origem: 'formulario',
    competencias: ['2025-11'],
    orcamento: 485000,
    criado_em: '2025-11-24T14:02:00Z',
    regra: {
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

describe('SimulateView', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('renderiza a tela de simulação', async () => {
    const job = criarJob()
    consultarJob.mockResolvedValue(job)

    const router = criarRouterDeTeste()

    await router.push('/jobs/job-1')
    await router.isReady()

    const wrapper = mount(SimulateView, {
      global: {
        plugins: [router],
      },
    })

  await vi.waitFor(() => {
    expect(wrapper.find('#loja').element).toHaveProperty('value', 'Loja 1')
  })

  expect(wrapper.text()).toContain('Simulação')
  expect(wrapper.text()).toContain('Regra estruturada')
  expect(wrapper.text()).toContain('Dados da simulação')

  expect(wrapper.find('#vigencia').element).toHaveProperty(
    'value',
    '11/2025',
  )
  expect(wrapper.find('#loja').element).toHaveProperty(
    'value',
    'Loja 1',
  )
  expect(wrapper.find('#marca').element).toHaveProperty(
    'value',
    'Marca 1',
  )
  expect(wrapper.find('#cargo').element).toHaveProperty(
    'value',
    'Cargo 1',
  )
  expect(wrapper.find('#meta').element).toHaveProperty(
    'value',
    'R$ 485.000,00',
  )
  expect(wrapper.find('#percentual').element).toHaveProperty(
    'value',
    '10%',
  )
  expect(wrapper.find('#totalComissionamento').element).toHaveProperty(
    'value',
    'R$ 492.100,00',
  )

  expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
  expect(wrapper.text()).toContain('Seguir para Finalização')

  expect(consultarJob).toHaveBeenCalledWith('job-1')
  })
})