import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { apiClient } from '@/services/api'
import { jobFixture, regraFixture } from '@/services/job.fixtures'
import type { JobResumo } from '@/types/api'
import HistoricoJobsView from './HistoricoJobsView.vue'

const { listarTodosOsJobs, rota, roteador } = vi.hoisted(() => ({
  listarTodosOsJobs: vi.fn<() => Promise<JobResumo[]>>(),
  rota: { name: 'regras-salvas' },
  roteador: { push: vi.fn<(destino: unknown) => Promise<void>>() },
}))

vi.mock('../services/historicoJobs.api', () => ({ listarTodosOsJobs }))

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => rota,
  useRouter: () => roteador,
}))

beforeEach(() => {
  vi.resetAllMocks()
  rota.name = 'regras-salvas'
  vi.mocked(apiClient.consultarJob).mockImplementation(async (id) => jobFixture({ id }))
})

function botaoDeReprocessamento(conteiner: VueWrapper) {
  return conteiner
    .findAll('button')
    .find((botao) => botao.text() === 'Reprocessar regra com novo orçamento')
}

function criarResumoDoJob(numero: number, status: JobResumo['status'] = 'liberado'): JobResumo {
  return {
    id: `0000000${numero}-1234-4000-8000-000000000000`,
    status,
    competencias: ['2025-09'],
    orcamento: 485000,
    criado_em: '2026-09-19T12:00:00Z',
    veredito: 'viavel',
  }
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

describe('HistoricoJobsView', () => {
  it('abre o formulário com a regra do job ao reprocessar com novo orçamento', async () => {
    rota.name = 'regras-arquivadas'
    const resumo = criarResumoDoJob(1, 'arquivado')
    listarTodosOsJobs.mockResolvedValue([resumo])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)
    await flushPromises()

    await botaoDeReprocessamento(conteiner)?.trigger('click')

    expect(roteador.push).toHaveBeenCalledWith({
      name: 'nova-regra',
      query: { reprocessar: resumo.id },
    })
    conteiner.unmount()
  })

  it('troca o selo de status pelo botão nas arquivadas', async () => {
    rota.name = 'regras-arquivadas'
    listarTodosOsJobs.mockResolvedValue([criarResumoDoJob(1, 'arquivado')])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)
    await flushPromises()

    const cartao = conteiner.get('article')
    expect(cartao.text()).toContain('Reprocessar regra com novo orçamento')
    expect(cartao.text()).not.toContain('Arquivado')
    conteiner.unmount()
  })

  it('não oferece o reprocessamento nas regras salvas', async () => {
    listarTodosOsJobs.mockResolvedValue([criarResumoDoJob(1)])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)
    await flushPromises()

    expect(conteiner.get('article').text()).toContain('Regra 00000001')
    expect(conteiner.get('article').text()).toContain('Liberado')
    expect(botaoDeReprocessamento(conteiner)).toBeUndefined()
    conteiner.unmount()
  })

  it.each([
    ['regras-salvas', 'liberado'],
    ['regras-arquivadas', 'arquivado'],
  ] as const)('mostra somente a versão mais recente, sem repetir a prévia em %s', async (nome, status) => {
    rota.name = nome
    const resumo = criarResumoDoJob(1, status)
    const anterior = regraFixture(1)
    anterior.representacao.nucleo.loja = ['Loja anterior']
    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['Loja atual']
    recente.representacao.especificacoes = [{
      ref: 'bonus-1',
      construto: 'bonus_fixo',
      alvo: { tipo: 'lista', valor: ['13'] },
      valor: 250,
    }]
    listarTodosOsJobs.mockResolvedValue([resumo])
    vi.mocked(apiClient.consultarJob).mockResolvedValue(
      jobFixture({ ...resumo, regras: [anterior, recente] }),
    )

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)
    await flushPromises()

    const cartao = conteiner.get('article')
    expect(cartao.text()).not.toContain('Loja anterior')
    expect(cartao.findAll('li').map((linha) => linha.text())).toEqual([
      'vigência = 11/2025',
      'loja = Loja atual',
      'marca = 10',
      'cargo = 100',
      '% de comissionamento = 2.5%',
      'bônus fixo = R$ 250,00',
    ])
    conteiner.unmount()
  })

  it('mantém o cartão e o acesso ao relatório quando o job ainda não possui regras', async () => {
    const resumo = criarResumoDoJob(1)
    listarTodosOsJobs.mockResolvedValue([resumo])
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ ...resumo, regras: [] }))

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)
    await flushPromises()

    const cartao = conteiner.get('article')
    expect(cartao.get('h2').text()).toBe('Regra 00000001')
    expect(cartao.findAll('li')).toHaveLength(0)
    expect(cartao.get('a').attributes('href')).toBe(`/jobs/${resumo.id}`)
    conteiner.unmount()
  })

  it('exibe apenas as regras salvas, com os contadores reais da sidebar', async () => {
    listarTodosOsJobs.mockResolvedValue([
      criarResumoDoJob(1),
      criarResumoDoJob(2),
      criarResumoDoJob(3, 'arquivado'),
    ])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)

    await vi.waitFor(() => {
      expect(conteiner.get('.tela-de-negocio').classes()).toContain('tela-de-negocio')
      expect(conteiner.text()).toContain('Salvas')
      expect(conteiner.text()).toContain('Regra 00000001')
      expect(conteiner.text()).not.toContain('Regra 00000003')
      expect(conteiner.text()).toContain('Salvas2')
      expect(conteiner.text()).toContain('Arquivadas1')
    })
  })

  it('pagina a lista quando há mais de seis regras', async () => {
    listarTodosOsJobs.mockResolvedValue(Array.from({ length: 7 }, (_, indice) => criarResumoDoJob(indice + 1)))

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)

    await vi.waitFor(() => expect(conteiner.text()).toContain('Página 1 de 2'))
    expect(conteiner.text()).not.toContain('Regra 00000007')

    const botaoProxima = conteiner.findAll('button').find((botao) => botao.text() === 'Próxima')
    expect(botaoProxima).toBeDefined()
    await botaoProxima?.trigger('click')

    expect(conteiner.text()).toContain('Página 2 de 2')
    expect(conteiner.text()).toContain('Regra 00000007')
  })

  it('mantém a busca e o filtro desabilitados enquanto a API não os suporta', async () => {
    listarTodosOsJobs.mockResolvedValue([])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)

    await vi.waitFor(() => expect(conteiner.find('input[type="search"]').exists()).toBe(true))

    expect(conteiner.get('input[type="search"]').attributes('disabled')).toBeDefined()
    expect(conteiner.get('button[title*="filtro"]').attributes('disabled')).toBeDefined()
  })
})
