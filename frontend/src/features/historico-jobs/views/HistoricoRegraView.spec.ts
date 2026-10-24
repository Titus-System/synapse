import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { consultarDetalhamento } from '@/services/detalhamento'
import { HttpError } from '@/services/http'
import TheSidebar from '@/components/TheSidebar.vue'
import { jobFixture, regraFixture, respostaPendente } from '@/services/job.fixtures'
import type { DetalhamentoSimulacao, Job } from '@/types/api'
import HistoricoRegraView from './HistoricoRegraView.vue'
vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
  },
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
async function montar(job = encerrado(), nome?: string) {
  vi.mocked(apiClient.consultarJob).mockResolvedValueOnce(job)
  vi.mocked(apiClient.listarJobs).mockResolvedValue({
    itens: [
      {
        id: job.id,
        nome,
        status: job.status,
        competencias: [],
        criado_em: job.criado_em,
      },
    ],
    pagina: 0,
    tamanho: 100,
    total: 1,
  })
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
    global: { plugins: [router], stubs: { TheSidebar: true, TheProcessHeader: true } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}
async function expandir(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('[aria-controls="simulacoes-do-historico"]').trigger('click')
}
function camposDaVersao(wrapper: ReturnType<typeof mount>, versao: number) {
  const secao = wrapper.get(`[aria-labelledby="titulo-versao-regra-${versao}"]`)
  return Object.fromEntries(
    secao.findAll('dl > div').map((campo) => [campo.get('dt').text(), campo.get('dd').text()]),
  )
}
it('identifica a versão salva pelo resultado vigente mesmo havendo versão maior', async () => {
  const { wrapper } = await montar()
  expect(wrapper.get('h1').text()).toBe('Regra Final')
  expect(wrapper.get('#resumo-regra-historica header').text()).not.toContain('Versão')
  expect(wrapper.text()).toContain('PRETO')
  const alternar = wrapper.get('[aria-controls="simulacoes-do-historico"]')
  expect(alternar.attributes('aria-expanded')).toBe('false')
  expect(wrapper.find('#simulacoes-do-historico').exists()).toBe(false)
  await expandir(wrapper)
  expect(alternar.attributes('aria-expanded')).toBe('true')
  expect(
    wrapper.findAll('#simulacoes-do-historico > section > header h2').map((item) => item.text()),
  ).toEqual(['Regra Final', 'Regra Descartada', 'Regra Descartada'])
  expect(wrapper.get('#titulo-versao-regra-2').text()).toBe('Regra Final')
  expect(wrapper.get('#simulacoes-do-historico').text()).not.toMatch(/Versão|Ver lógica/)
  expect(camposDaVersao(wrapper, 2)).toMatchObject({
    'Meta de vendas': 'R$ 1.000.000,00',
    'Orçamento de comissão': 'R$ 30.000,00',
  })
  expect(wrapper.get('[aria-label="Resultado histórico da versão 2"]').text()).toContain(
    'Resultado: Regra de negócio aprovada!',
  )
  expect(wrapper.get('[role="status"]').classes()).toContain(
    'border-l-[#14532D]',
  )
  expect(wrapper.findComponent(TheSidebar).props('secaoAtiva')).toBe('salvas')
  expect(wrapper.findComponent(TheSidebar).props('quantidadeSalvas')).toBe(1)
  expect(wrapper.findComponent(TheSidebar).props('regrasRecentes')).toMatchObject([
    { identificador: 'job-1' },
  ])
  expect(wrapper.text()).not.toMatch(/9\.000\.000|888\.888/)
  for (const acao of ['Editar', 'Salvar'])
    expect(wrapper.findAll('button').map((b) => b.text())).not.toContain(acao)
  await expandir(wrapper)
  expect(wrapper.find('#simulacoes-do-historico').exists()).toBe(false)
  expect(apiClient.consultarJob).toHaveBeenCalledTimes(1)
  expect(consultarDetalhamento).not.toHaveBeenCalled()
})
it('mostra encerramento arquivado sem atribuir a ele uma execução anterior', async () => {
  const { wrapper } = await montar(encerrado('arquivado'))
  expect(wrapper.get('h1').text()).toBe('Versão 3')
  expect(wrapper.text()).toContain('arquivada')
  expect(wrapper.text()).toContain('Sem simulação disponível')
  expect(wrapper.find('[aria-controls="relatorio-simulacao"]').exists()).toBe(false)
  await expandir(wrapper)
  expect(wrapper.get('#titulo-versao-regra-3').text()).toBe('Versão de encerramento')
  const resultado = wrapper.get('[aria-label="Resultado histórico da versão 3"]')
  expect(resultado.text()).toContain('Sem simulação disponível')
  expect(resultado.text()).not.toContain('R$')
  expect(wrapper.findAll('h2').map((item) => item.text())).not.toContain('Regra Final')
})
it('associa execuções por regra sem usar parâmetros atuais como snapshots históricos', async () => {
  const { wrapper } = await montar()
  await expandir(wrapper)
  expect(camposDaVersao(wrapper, 1)['Meta de vendas']).toBe('Não registrada neste resultado')
  expect(wrapper.get('[aria-label="Resultado histórico da versão 3"]').text()).toContain(
    'Sem simulação disponível',
  )
})
it('permite selecionar execuções da mesma versão e destaca somente a vigente', async () => {
  const job = encerrado()
  job.simulacoes!.push({ ...job.simulacao!, id: 'segunda-execucao' })
  const { wrapper } = await montar(job)
  await expandir(wrapper)
  const execucoes = wrapper.get('select')
  expect(execucoes.findAll('option')).toHaveLength(2)
  expect(execucoes.element).toHaveProperty('value', 'simulacao-1')
  expect(
    execucoes.findAll('option').filter((o) => o.text().includes('Resultado vigente')),
  ).toHaveLength(1)
  await execucoes.setValue('segunda-execucao')
  expect(execucoes.element).toHaveProperty('value', 'segunda-execucao')
})
it('mostra o aceite da meta na regra final e somente na execução correspondente', async () => {
  const job = encerrado()
  const aceitaEm = '2026-10-22T21:42:50Z'
  job.simulacao!.meta_sugerida_aceita_em = aceitaEm
  job.simulacao!.meta_venda = 61688188.96958572
  const original = { ...job.simulacao! }
  delete original.meta_sugerida_aceita_em
  job.simulacoes!.push({ ...original, id: 'antes-do-aceite', meta_venda: 30000000 })
  const { wrapper } = await montar(job)
  const resumo = () => wrapper.get('#resumo-regra-historica')
  expect(resumo().text()).toContain('Meta de vendas sugerida aceita')
  expect(resumo().text()).toContain('R$ 61.688.188,97')
  expect(resumo().get('time').attributes('datetime')).toBe(aceitaEm)
  expect(resumo().get('time').text()).toBe(
    new Date(aceitaEm).toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    }),
  )
  await expandir(wrapper)
  const resultado = () => wrapper.get('[aria-label="Resultado histórico da versão 2"]')
  expect(resultado().text()).toContain('Meta de vendas sugerida aceita')
  expect(resultado().get('time').attributes('datetime')).toBe(aceitaEm)
  expect(wrapper.get('[aria-label="Resultado histórico da versão 1"]').text()).not.toContain(
    'Meta de vendas sugerida aceita',
  )
  await wrapper.get('select').setValue('antes-do-aceite')
  expect(resumo().text()).not.toContain('Meta de vendas sugerida aceita')
  expect(resultado().text()).not.toContain('Meta de vendas sugerida aceita')
  expect(resumo().text()).toContain('R$ 30.000.000,00')
  await wrapper.get('select').setValue('simulacao-1')
  expect(resumo().text()).toContain('Meta de vendas sugerida aceita')
})
it('não atribui aceite a um histórico sem esse registro mesmo com metas diferentes', async () => {
  const { wrapper } = await montar()
  await expandir(wrapper)
  expect(wrapper.text()).not.toContain('Meta de vendas sugerida aceita')
  expect(wrapper.find('time').exists()).toBe(false)
})
it('exibe a regra final e a descartada pelo aceite da meta com os valores próprios', async () => {
  const job = encerrado()
  job.simulacao!.meta_venda = 61688188.96958572
  job.simulacao!.meta_sugerida_aceita_em = '2026-10-23T00:42:50Z'
  job.simulacao!.resultado!.totais!.simulado = 2498539.55
  job.simulacao!.anterior_a_meta_sugerida = {
    resultado_id: 'resultado-original',
    criado_em: '2026-10-22T23:41:37Z',
    status: 'sucesso', veredito: 'viavel', meta_venda: 30000000,
    resultado: {
      ...job.simulacao!.resultado!,
      totais: { ...job.simulacao!.resultado!.totais!, simulado: 1227664.86 },
    },
  }
  const { wrapper } = await montar(job)
  await expandir(wrapper)
  const atual = wrapper.get('[aria-label="Resultado histórico da versão 2"]')
  const anterior = wrapper.get('[aria-label="Resultado anterior da versão 2"]')
  expect(atual.text()).toContain('R$ 2.498.539,55')
  expect(anterior.text()).toContain('R$ 1.227.664,86')
  expect(anterior.text()).not.toContain('Resultado vigente')
  expect(wrapper.get('#titulo-versao-regra-2').text()).toBe('Regra Final')
  const secaoAnterior = wrapper.get('[aria-labelledby="titulo-versao-regra-2-anterior"]')
  expect(secaoAnterior.get('h2').text()).toBe('Regra Descartada')
  expect(secaoAnterior.text()).toContain('R$ 30.000.000,00')
  expect(wrapper.get('#simulacoes-do-historico').text()).not.toMatch(/Versão|Ver lógica|não escolhido/)
  expect(wrapper.get('h1').text()).toBe('Regra Final')
  expect(wrapper.get('#resumo-regra-historica').text()).toContain('R$ 61.688.188,97')
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  await flushPromises()
  expect(consultarDetalhamento).toHaveBeenLastCalledWith('job-1', 'simulacao-1', expect.any(AbortSignal))
})
it('informa versões e vínculos ausentes sem inventar a versão final', async () => {
  const job = encerrado()
  job.regras = []
  const { wrapper } = await montar(job)
  expect(wrapper.text()).toContain('não identificam a versão final salva')
  expect(wrapper.text()).toContain('resultado sem vínculo conhecido')
  expect(wrapper.text()).toContain('Nenhuma versão disponível')
})
it('não classifica versões como finais ou descartadas quando falta o vínculo do resultado vigente', async () => {
  const job = encerrado()
  job.simulacao!.regra_id = 'regra-desconhecida'
  const { wrapper } = await montar(job)
  await expandir(wrapper)
  expect(wrapper.text()).toContain('não identificam a versão final salva')
  const titulos = wrapper
    .findAll('#simulacoes-do-historico > section > header h2')
    .map((item) => item.text())
  expect(titulos).toEqual(['Versão registrada', 'Versão registrada', 'Versão registrada'])
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
it('cancela o detalhamento ao trocar a execução e descarta a resposta antiga', async () => {
  const pendente = respostaPendente<DetalhamentoSimulacao>()
  vi.mocked(consultarDetalhamento).mockReturnValueOnce(pendente.promise)
  const job = encerrado()
  job.simulacoes!.push({ ...job.simulacao!, id: 'segunda-execucao' })
  const { wrapper } = await montar(job)
  await wrapper.get('[aria-controls="relatorio-simulacao"]').trigger('click')
  expect(consultarDetalhamento).toHaveBeenCalledWith(
    'job-1',
    'simulacao-1',
    expect.any(AbortSignal),
  )
  const sinal = vi.mocked(consultarDetalhamento).mock.calls[0]![2]!
  await expandir(wrapper)
  await wrapper.get('select').setValue('segunda-execucao')
  await flushPromises()
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
it('exibe na barra lateral o nome da regra e, sem nome, o rótulo com a data', async () => {
  const job = encerrado()
  const comNome = await montar(job, 'Comissão de novembro')
  expect(comNome.wrapper.findComponent(TheSidebar).props('regrasRecentes')).toEqual([
    { identificador: 'job-1', rotulo: 'Comissão de novembro', destino: '/jobs/job-1' },
  ])
  vi.resetAllMocks()
  const semNome = await montar(encerrado())
  expect(semNome.wrapper.findComponent(TheSidebar).props('regrasRecentes')).toEqual([
    {
      identificador: 'job-1',
      rotulo: `Regra · ${new Date(job.criado_em).toLocaleDateString('pt-BR')}`,
      destino: '/jobs/job-1'
    },
  ])
})
