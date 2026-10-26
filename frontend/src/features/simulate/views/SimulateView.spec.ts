import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount } from '@vue/test-utils'
import SimulateView from './SimulateView.vue'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { usarStoreJobAtual } from '@/stores/currentJob'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { consultarDetalhamento } from '@/services/detalhamento'
import type { Job } from '@/types/api'

vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))

vi.mock('@/services/detalhamento', () => ({
  consultarDetalhamento: vi.fn<typeof import('@/services/detalhamento').consultarDetalhamento>(),
}))

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<(id: string, signal?: AbortSignal) => Promise<Job>>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>().mockResolvedValue({
      itens: [],
      pagina: 0,
      tamanho: 100,
      total: 0,
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
        path: '/jobs/:id/correcao',
        name: 'correcao-regra',
        component: { template: '<div />' },
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
      {
        path: '/salvas',
        name: 'regras-salvas',
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
            loja: ['1'],
            marca: ['10'],
            cargo: ['100'],
            percentual: 0.1,
          },
          especificacoes: [],
        },
      },
    ],
    simulacao: {
      id: 'simulacao-1',
      regra_id: 'regra-1',
      meta_venda: 1000000,
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

async function montarInterrompido(motivo: string | null = null) {
  const job = { ...criarJob(), status: 'erro' as const, simulacao: null, motivo }
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
  return { wrapper, store: usarStoreJobAtual(pinia) }
}

describe('SimulateView', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('anuncia a parada do job como desfecho, e não como falha da tela', async () => {
    const { wrapper } = await montarInterrompido()

    expect(wrapper.get('main h2').text()).toBe('Processamento interrompido')
    expect(wrapper.text()).toContain('Esta regra falhou antes de produzir um resultado.')
    expect(wrapper.text()).not.toContain('Não foi possível carregar a simulação')
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('LOJA-1')
    const campos = wrapper.findAll('dl > div').map((campo) => ({
      rotulo: campo.get('dt').text(),
      valor: campo.get('dd').text(),
    }))
    expect(campos).toEqual(
      expect.arrayContaining([
        { rotulo: 'Meta de vendas', valor: 'Não informada' },
        { rotulo: 'Orçamento de comissão', valor: 'R$ 485.000,00' },
      ]),
    )

    const acoes = wrapper
      .findAll('main a')
      .map((link) => ({ href: link.attributes('href'), texto: link.text() }))
    expect(acoes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ href: '/nova-regra', texto: 'Começar uma nova regra' }),
        expect.objectContaining({ href: '/salvas', texto: 'Ver minhas regras' }),
      ]),
    )
    wrapper.unmount()
  })

  it('mostra a razão de indisponibilidade do serviço de IA sem termos técnicos', async () => {
    const razao =
      'O serviço de inteligência artificial ficou indisponível por muito tempo e a regra não foi processada. Envie a regra de novo mais tarde.'
    const { wrapper } = await montarInterrompido(razao)

    const texto = wrapper.get('main').text()
    expect(texto).toContain(razao)
    for (const proibido of [
      'provedor_indisponivel',
      'gerando_regra',
      'geracao_codigo',
      '503',
      'Gemini',
    ]) {
      expect(texto).not.toContain(proibido)
    }
    wrapper.unmount()
  })

  it('mostra a razão localizada da parada no lugar do texto padrão', async () => {
    const { wrapper } = await montarInterrompido(
      'A regra usa um elemento sem implementação correspondente.',
    )

    expect(wrapper.text()).toContain('A regra usa um elemento sem implementação correspondente.')
    expect(wrapper.text()).not.toContain('Esta regra falhou antes de produzir um resultado.')
    wrapper.unmount()
  })

  it('prioriza a falha de carregamento sobre o desfecho do job interrompido', async () => {
    const { wrapper, store } = await montarInterrompido()

    consultarJob.mockRejectedValueOnce(
      new HttpError(500, 'Não foi possível consultar o processamento.'),
    )
    await store.consultarJob()
    await flushPromises()

    expect(wrapper.get('main h2').text()).toBe('Não foi possível carregar a simulação')
    expect(wrapper.text()).toContain('Não foi possível consultar o processamento.')
    wrapper.unmount()
  })

  it.each([
    ['aguardando_transcricao', 403],
    ['aguardando_transcricao', 500],
    ['gerando_regra', 403],
    ['gerando_regra', 500],
    ['simulando', 403],
    ['simulando', 500],
  ] as const)(
    'exibe o erro de consulta durante %s quando a API responde %i',
    async (status, codigo) => {
      const { wrapper, store } = await montarProcessamento(status)
      expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)

      consultarJob.mockRejectedValueOnce(
        new HttpError(codigo, 'Não foi possível consultar o processamento.'),
      )
      await store.consultarJob()
      await flushPromises()

      expect(store.job?.status).toBe(status)
      expect(wrapper.get('main h2').text()).toBe('Não foi possível carregar a simulação')
      expect(wrapper.text()).toContain('Não foi possível consultar o processamento.')
      expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
      expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(false)
      wrapper.unmount()
    },
  )

  it('retoma o progresso e mostra o resultado após recuperar uma consulta com falha', async () => {
    const { wrapper, job, store } = await montarProcessamento()
    consultarJob.mockRejectedValueOnce(
      new HttpError(500, 'Não foi possível consultar o processamento.'),
    )
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
    const job = { ...criarJob(), meta_venda: 2000000, orcamento: 600000 }
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
      expect(wrapper.find('#loja').element).toHaveProperty('value', 'LOJA-1')
    })

    expect(wrapper.text()).toContain('Simulação')
    expect(wrapper.text()).toContain('Regra estruturada')
    expect(wrapper.text()).toContain('Dados da simulação')

    expect(wrapper.find('#vigencia').element).toHaveProperty('value', '11/2025')
    expect(wrapper.find('#loja').element).toHaveProperty('value', 'LOJA-1')
    expect(wrapper.find('#marca').element).toHaveProperty('value', 'PRETO')
    expect(wrapper.find('#cargo').element).toHaveProperty('value', 'VENDEDOR LOJA')
    expect(wrapper.find('#meta').element).toHaveProperty('value', 'R$ 1.000.000,00')
    expect(wrapper.get('label[for="meta"]').text()).toBe('Meta de vendas')
    expect(wrapper.get('label[for="orcamento"]').text()).toBe('Orçamento de comissão')
    expect(wrapper.get('#orcamento').element).toHaveProperty('value', 'R$ 485.000,00')
    expect(wrapper.find('#percentual').element).toHaveProperty('value', '10%')
    expect(wrapper.find('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')

    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    expect(wrapper.text()).toContain('Seguir para Finalização')

    expect(consultarJob).toHaveBeenCalledWith('job-1')
  })
})

it('abre a conversa sem clique ao reabrir um job que aguarda correção', async () => {
  consultarJob.mockResolvedValue({
    ...criarJob(),
    status: 'aguardando_confirmacao_parametros',
    simulacao: null,
  })
  const router = criarRouterDeTeste()
  await router.push('/jobs/job-1')
  const wrapper = mount(SimulateView, {
    global: { plugins: [router, createPinia()], stubs: { FontAwesomeIcon: true } },
  })
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/jobs/job-1/correcao')
  expect(wrapper.text()).not.toContain('Corrigir por texto ou voz')
  wrapper.unmount()
})

it('abre a conversa quando o job pausa por conflito durante o acompanhamento', async () => {
  consultarJob.mockResolvedValue({ ...criarJob(), status: 'gerando_regra', simulacao: null })
  const router = criarRouterDeTeste()
  await router.push('/jobs/job-1')
  const wrapper = mount(SimulateView, {
    global: { plugins: [router, createPinia()], stubs: { FontAwesomeIcon: true } },
  })
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/jobs/job-1')
  const chamadas = vi.mocked(abrirAcompanhamentoJob).mock.calls
  const handlers = chamadas[chamadas.length - 1]![1]
  handlers.onEstado({
    job_id: 'job-1',
    status: 'aguardando_confirmacao_parametros',
    status_anterior: 'gerando_regra',
  })
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/jobs/job-1/correcao')
  wrapper.unmount()
})

it('abre os filtros e a tabela no popup sem a representação técnica', async () => {
  consultarJob.mockResolvedValue(criarJob())
  vi.mocked(consultarDetalhamento).mockResolvedValue({
    simulacao_id: 'simulacao-1',
    linhas: {
      '2025-11': {
        'COL-0001': {
          cod_loja: '1',
          cod_marca: '10',
          cod_cargo: '100',
          comissao_baseline: 100,
          comissao_simulada: 150,
          diferenca: 50,
          contribuicoes: { 'nucleo.percentual': 50 },
        },
      },
    },
  })
  const router = criarRouterDeTeste()
  await router.push('/jobs/job-1')
  const wrapper = mount(SimulateView, {
    global: { plugins: [router, createPinia()], stubs: { FontAwesomeIcon: true } },
  })
  await flushPromises()
  expect(wrapper.text()).not.toContain('LÓGICA ESTRUTURADA')
  expect(consultarDetalhamento).not.toHaveBeenCalled()
  await wrapper
    .findAll('button')
    .find((botao) => botao.text().includes('Abrir relatório'))!
    .trigger('click')
  await flushPromises()
  expect(consultarDetalhamento).toHaveBeenCalledWith(
    'job-1',
    'simulacao-1',
    expect.any(AbortSignal),
  )
  expect(wrapper.find('table').exists()).toBe(false)
  await wrapper.get('dialog form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('COL-0001')
  wrapper.unmount()
})
