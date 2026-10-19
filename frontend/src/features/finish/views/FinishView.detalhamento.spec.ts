import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { jobFixture, regraFixture, respostaPendente } from '@/services/job.fixtures'
import type { DetalhamentoSimulacao, ResultadoLinhas } from '@/types/api'
import FinishView from './FinishView.vue'

vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: async () => 'token-teste',
  iniciarLogin: vi.fn<() => void>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    listarJobs: vi
      .fn<typeof apiClient.listarJobs>()
      .mockResolvedValue({ itens: [], total: 0, pagina: 0, tamanho: 100 }),
  },
}))
vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: () => ({ fechar: () => undefined }),
}))

const montagens: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture())
})
afterEach(() => {
  for (const wrapper of montagens.splice(0)) wrapper.unmount()
  vi.restoreAllMocks()
})

function linhasDeTeste(quantidade = 1): ResultadoLinhas {
  return {
    '2025-11': Object.fromEntries(
      Array.from({ length: quantidade }, (_, indice) => [
        `COL-${String(indice).padStart(4, '0')}`,
        {
          cod_loja: '013',
          cod_marca: '010',
          cod_cargo: '100',
          comissao_baseline: 100,
          comissao_simulada: 150,
          diferenca: 49.99,
          contribuicoes: { 'nucleo.percentual': 40, 'elem.7': 9.99 },
        },
      ]),
    ),
  }
}

function responder(linhas?: ResultadoLinhas) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        simulacao_id: 'simulacao-1',
        ...(linhas ? { linhas } : {}),
      }),
    ),
  )
}

async function montar() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/jobs/:id/finalizar', component: FinishView }],
  })
  await router.push('/jobs/job-1/finalizar')
  const wrapper = mount(FinishView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { TheSidebar: true, TheProcessHeader: true },
    },
  })
  montagens.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}

it('abre o relatório da simulação visível e usa a versão correta da regra', async () => {
  const original = regraFixture()
  original.representacao.especificacoes = [{ ref: 'elem.7', construto: 'bonus_fixo', valor: 9.99 }]
  const nova = regraFixture(2)
  nova.representacao.nucleo.percentual = 0.9
  const job = jobFixture({ regras: [nova, original] })
  job.simulacao!.regra_id = original.id
  vi.mocked(apiClient.consultarJob).mockResolvedValue(job)
  const fetch = responder(linhasDeTeste())
  const { wrapper } = await montar()
  expect(fetch).not.toHaveBeenCalled()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  const relatorio = wrapper.get('#relatorio-simulacao')
  expect(relatorio.text()).toContain('11/2025')
  expect(relatorio.text()).toContain('COL-0000')
  expect(relatorio.text()).toContain('R$ 49,99')
  expect(relatorio.text()).toContain('Comissão de 2,5%')
  expect(relatorio.text()).toContain('Bônus fixo')
  expect(relatorio.text()).not.toMatch(/nucleo\.percentual|elem\.7|simulacao-1|job-1|90%/)
  expect(fetch.mock.calls[0]![0]).toMatch(/\/jobs\/job-1\/simulacoes\/simulacao-1\/linhas$/)
})

it('mostra a venda de cada linha como vem da api e um traço nas linhas gravadas sem ela', async () => {
  const linhas = linhasDeTeste(3)
  const novembro = linhas['2025-11']!
  novembro['COL-0000']!.vendas = 24785.01
  novembro['COL-0001']!.vendas = 0
  responder(linhas)
  const { wrapper } = await montar()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  const cabecalho = wrapper.findAll('thead th').map((celula) => celula.text())
  expect(cabecalho.slice(0, 2)).toEqual(['Competência', 'Matrícula'])
  const coluna = cabecalho.indexOf('Venda')
  expect(cabecalho.slice(coluna - 1, coluna + 2)).toEqual(['Loja', 'Venda', 'Cargo'])
  const vendas = wrapper.findAll('tbody tr').map((linha) => linha.findAll('td')[coluna]!.text())
  expect(vendas).toEqual(['R$ 24.785,01', 'R$ 0,00', '—'])
})

it('mantém apenas 25 linhas na tabela de 2700 registros e pagina sem novas consultas', async () => {
  const fetch = responder(linhasDeTeste(2700))
  const { wrapper } = await montar()
  const abrir = wrapper.get('[aria-controls="relatorio-simulacao"]')
  await abrir.trigger('click')
  await flushPromises()
  expect(wrapper.findAll('tbody tr')).toHaveLength(25)
  await wrapper
    .findAll('button')
    .find((botao) => botao.text() === 'Próxima')!
    .trigger('click')
  expect(wrapper.find('tbody').text()).toContain('COL-0025')
  expect(wrapper.find('tbody').text()).not.toContain('COL-0000')
  expect(wrapper.findAll('tbody tr')).toHaveLength(25)
  await abrir.trigger('click')
  await abrir.trigger('click')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('informa quando a simulação antiga não tem detalhamento', async () => {
  responder()
  const { wrapper } = await montar()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('O detalhamento não está disponível para esta simulação.')
  expect(wrapper.find('table').exists()).toBe(false)
})

it('mostra o carregamento e permite tentar novamente após a recusa sanitizada', async () => {
  const resposta = respostaPendente<Response>()
  const fetch = vi.spyOn(globalThis, 'fetch').mockReturnValueOnce(resposta.promise)
  const { wrapper } = await montar()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('Carregando relatório...')
  resposta.resolve(
    new Response(
      JSON.stringify({
        codigo: 'simulacao_nao_encontrada',
        mensagem: 'segredo interno',
      }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    ),
  )
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain(
    'Não foi possível encontrar a simulação solicitada.',
  )
  expect(wrapper.text()).not.toContain('segredo interno')
  fetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ simulacao_id: 'simulacao-1', linhas: linhasDeTeste() })),
  )
  await wrapper
    .findAll('button')
    .find((botao) => botao.text() === 'Tentar novamente')!
    .trigger('click')
  await flushPromises()
  expect(wrapper.find('table').exists()).toBe(true)
})

it.each(['erro_codigo', 'assercao_violada', 'erro_infra'] as const)(
  'não oferece relatório para %s',
  async (status) => {
    const job = jobFixture()
    job.simulacao!.status = status
    vi.mocked(apiClient.consultarJob).mockResolvedValue(job)
    const fetch = responder()
    const { wrapper } = await montar()
    expect(wrapper.find('[aria-controls="relatorio-simulacao"]').exists()).toBe(false)
    expect(fetch).not.toHaveBeenCalled()
  },
)

it('descarta a resposta antiga quando a rota muda para outro job', async () => {
  const resposta = respostaPendente<Response>()
  const fetch = vi.spyOn(globalThis, 'fetch').mockReturnValue(resposta.promise)
  const { wrapper, router } = await montar()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  const sinal = fetch.mock.calls[0]![1]!.signal!
  vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ id: 'job-2' }))
  await router.push('/jobs/job-2/finalizar')
  await flushPromises()
  expect(sinal.aborted).toBe(true)
  const antigo: DetalhamentoSimulacao = { simulacao_id: 'simulacao-1', linhas: linhasDeTeste() }
  resposta.resolve(new Response(JSON.stringify(antigo)))
  await flushPromises()
  expect(wrapper.find('#relatorio-simulacao').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('COL-0000')
})
