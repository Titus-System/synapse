import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { JobResumo } from '@/types/api'
import HistoricoJobsView from './HistoricoJobsView.vue'

const { listarTodosOsJobs } = vi.hoisted(() => ({
  listarTodosOsJobs: vi.fn<() => Promise<JobResumo[]>>(),
}))

vi.mock('../services/historicoJobs.api', () => ({ listarTodosOsJobs }))

const nomeDaRota = 'regras-salvas'

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: nomeDaRota }),
}))

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
    stubs: {
      RouterLink: {
        props: ['to'],
        template: '<a :href="to"><slot /></a>',
      },
    },
  },
}

describe('HistoricoJobsView', () => {
  it('exibe apenas as regras salvas, com os contadores reais da sidebar', async () => {
    listarTodosOsJobs.mockResolvedValue([
      criarResumoDoJob(1),
      criarResumoDoJob(2),
      criarResumoDoJob(3, 'arquivado'),
    ])

    const conteiner = mount(HistoricoJobsView, opcoesDeMontagem)

    await vi.waitFor(() => {
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
