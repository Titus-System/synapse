import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { consultarDetalhamento } from '@/services/detalhamento'
import { HttpError } from '@/services/http'
import { jobFixture, regraFixture, respostaPendente } from '@/services/job.fixtures'
import type { DetalhamentoSimulacao, Job } from '@/types/api'
import HistoricoRegraView from './HistoricoRegraView.vue'
vi.mock('@/services/api', () => ({
  apiClient: { consultarJob: vi.fn<typeof apiClient.consultarJob>() },
}))
vi.mock('@/services/detalhamento', () => ({
  consultarDetalhamento: vi.fn<typeof consultarDetalhamento>(),
}))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  vi.resetAllMocks()
})
function encerrado(status: 'liberado' | 'arquivado' = 'liberado') {
  const job = jobFixture({
    status,
    regras: [regraFixture(3), regraFixture(1), regraFixture(2)],
    meta_venda: 9000000,
    orcamento: 888888,
  })
  job.simulacao!.regra_id = 'regra-2'
  job.simulacao!.meta_venda = 1000000
  job.simulacao!.resultado!.totais!.orcamento = 30000
  job.simulacoes = [
    { ...job.simulacao!, id: 'execucao-anterior', regra_id: 'regra-1', meta_venda: undefined },
  ]
  return job
}
async function montar(job = encerrado()) {
  vi.mocked(apiClient.consultarJob).mockResolvedValueOnce(job)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id/historico', component: HistoricoRegraView },
      { path: '/jobs/:id', component: { template: '<div>Processamento</div>' } },
      { path: '/jobs/:id/correcao', component: { template: '<div>Correção</div>' } },
    ],
  })
  await router.push('/jobs/job-1/historico')
  const wrapper = mount(HistoricoRegraView, {
    global: { plugins: [router], stubs: { TheSidebar: true } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
it('identifica a versão salva pelo resultado vigente mesmo havendo versão maior', async () => {
  const { wrapper } = await montar()
  expect(wrapper.findAll('select')[0]!.element).toHaveProperty('value', 'regra-2')
  expect(
    wrapper
      .findAll('select')[0]!
      .findAll('option')
      .map((item) => item.attributes('value')),
  ).toEqual(['regra-3', 'regra-2', 'regra-1'])
  expect(wrapper.get('h2').text()).toBe('Versão final salva')
  expect(wrapper.text()).toContain('PRETO')
  const resultado = wrapper.get('[aria-label="Resultado histórico"]').text()
  expect(resultado).toContain('Meta de vendas: R$ 1.000.000,00')
  expect(resultado).toContain('Orçamento: R$ 30.000,00')
  expect(resultado).not.toMatch(/9\.000\.000|888\.888/)
  expect(wrapper.findAll('button').map((b) => b.text())).not.toContain('Salvar')
})
it('mostra encerramento arquivado sem atribuir a ele uma execução anterior', async () => {
  const { wrapper } = await montar(encerrado('arquivado'))
  expect(wrapper.findAll('select')[0]!.element).toHaveProperty('value', 'regra-3')
  expect(wrapper.get('h2').text()).toContain('arquivada')
  expect(wrapper.text()).toContain('Sem simulação disponível')
  expect(wrapper.find('[aria-label="Resultado histórico"]').exists()).toBe(false)
  expect(wrapper.find('[aria-controls="relatorio-simulacao"]').exists()).toBe(false)
})
it('associa execuções por regra sem usar parâmetros atuais como snapshots históricos', async () => {
  const { wrapper } = await montar()
  await wrapper.findAll('select')[0]!.setValue('regra-1')
  expect(wrapper.get('h2').text()).toBe('Versão anterior / descartada')
  expect(wrapper.findAll('select')[1]!.element).toHaveProperty('value', 'execucao-anterior')
  expect(wrapper.get('[aria-label="Resultado histórico"]').text()).toContain(
    'Meta de vendas: Não registrada neste resultado',
  )
  await wrapper.findAll('select')[0]!.setValue('regra-3')
  expect(wrapper.text()).toContain('Sem simulação disponível')
  expect(wrapper.find('table').exists()).toBe(false)
})
it('permite selecionar execuções da mesma versão e destaca somente a vigente', async () => {
  const job = encerrado()
  job.simulacoes!.push({ ...job.simulacao!, id: 'segunda-execucao' })
  const { wrapper } = await montar(job)
  const execucoes = wrapper.findAll('select')[1]!
  expect(execucoes.findAll('option')).toHaveLength(2)
  expect(execucoes.element).toHaveProperty('value', 'simulacao-1')
  expect(
    execucoes.findAll('option').filter((o) => o.text().includes('Resultado vigente')),
  ).toHaveLength(1)
  await execucoes.setValue('segunda-execucao')
  expect(execucoes.element).toHaveProperty('value', 'segunda-execucao')
})
it('informa versões e vínculos ausentes sem inventar a versão final', async () => {
  const job = encerrado()
  job.regras = []
  const { wrapper } = await montar(job)
  expect(wrapper.text()).toContain('não identificam a versão final salva')
  expect(wrapper.text()).toContain('resultado sem vínculo conhecido')
  expect(wrapper.text()).toContain('Nenhuma versão disponível')
})
it.each(['gerando_regra', 'aguardando_confirmacao_parametros', 'cancelado'] as const)(
  'retorna %s ao fluxo correspondente',
  async (status) => {
    const { router, wrapper } = await montar(jobFixture({ status }))
    expect(router.currentRoute.value.path).toBe(
      `/jobs/job-1${status === 'aguardando_confirmacao_parametros' ? '/correcao' : ''}`,
    )
    expect(wrapper.text()).not.toContain('Regra salva.')
  },
)
it('mostra falha de consulta e permite tentar novamente', async () => {
  const { wrapper, router } = await montar()
  vi.mocked(apiClient.consultarJob).mockRejectedValueOnce(
    new HttpError(404, 'Não foi possível encontrar a regra solicitada.'),
  )
  await router.push('/jobs/job-2/historico')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível encontrar a regra')
  vi.mocked(apiClient.consultarJob).mockResolvedValueOnce(encerrado())
  await wrapper.get('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('Regra salva.')
})
it('cancela o detalhamento ao trocar versão e descarta a resposta antiga', async () => {
  const pendente = respostaPendente<DetalhamentoSimulacao>()
  vi.mocked(consultarDetalhamento).mockReturnValueOnce(pendente.promise)
  const { wrapper } = await montar()
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  expect(consultarDetalhamento).toHaveBeenCalledWith(
    'job-1',
    'simulacao-1',
    expect.any(AbortSignal),
  )
  const sinal = vi.mocked(consultarDetalhamento).mock.calls[0]![2]!
  await wrapper.findAll('select')[0]!.setValue('regra-1')
  expect(sinal.aborted).toBe(true)
  pendente.resolve({
    simulacao_id: 'simulacao-1',
    linhas: {
      '2025-11': {
        'PESSOA-ANTIGA': {
          cod_loja: '13',
          cod_marca: '10',
          cod_cargo: '100',
          comissao_baseline: 1,
          comissao_simulada: 2,
          diferenca: 1,
          contribuicoes: {},
        },
      },
    },
  })
  await flushPromises()
  expect(wrapper.text()).not.toContain('PESSOA-ANTIGA')
  expect(wrapper.find('table').exists()).toBe(false)
})
it('cancela a consulta anterior e não mistura respostas de jobs diferentes', async () => {
  const { wrapper, router } = await montar()
  const pendente = respostaPendente<Job>()
  vi.mocked(apiClient.consultarJob).mockReturnValueOnce(pendente.promise)
  await router.push('/jobs/job-2/historico')
  await flushPromises()
  const chamadas = vi.mocked(apiClient.consultarJob).mock.calls
  const sinal = chamadas[chamadas.length - 1]![1]!
  vi.mocked(apiClient.consultarJob).mockResolvedValueOnce(
    jobFixture({ id: 'job-3', status: 'arquivado', regras: [] }),
  )
  await router.push('/jobs/job-3/historico')
  await flushPromises()
  expect(sinal.aborted).toBe(true)
  pendente.resolve(encerrado())
  await flushPromises()
  expect(wrapper.text()).toContain('Regra arquivada.')
  expect(wrapper.text()).not.toContain('Versão final salva')
})
