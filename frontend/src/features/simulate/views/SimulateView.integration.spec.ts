import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  jobFixture,
  regraFixture,
  jobComSugestaoFixture,
  respostaPendente,
  jobSemOrcamentoFixture,
  jobComMetaFixture,
  jobMetaAceitaFixture,
  jobBuscandoMetaFixture,
  jobComTentativasFixture,
} from '@/services/job.fixtures'
import type { Job } from '@/types/api'
import SimulateView from './SimulateView.vue'
import { usarStoreJobAtual } from '@/stores/currentJob'

vi.mock('@/services/keycloak', () => ({
  obterTokenDeAcesso: vi.fn<() => Promise<string>>().mockResolvedValue('token-da-sessao'),
  iniciarLogin: vi.fn<() => Promise<void>>().mockResolvedValue(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))

class Stream {
  static atual: Stream
  private controlador!: ReadableStreamDefaultController<Uint8Array>
  readonly corpo = new ReadableStream<Uint8Array>({
    start: (controlador) => {
      this.controlador = controlador
    },
  })
  fechado = false

  constructor(
    readonly url: string,
    signal: AbortSignal,
  ) {
    Stream.atual = this
    signal.addEventListener(
      'abort',
      () => {
        this.fechado = true
        this.controlador.error(new DOMException('Cancelado', 'AbortError'))
      },
      { once: true },
    )
  }

  emitir(tipo: string, dados: unknown) {
    this.controlador.enqueue(
      new TextEncoder().encode(`event: ${tipo}\ndata: ${JSON.stringify(dados)}\n\n`),
    )
  }

  desconectar() {
    this.controlador.close()
  }
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function montar(
  consultar: () => Job | Promise<Job>,
  executar?: () => Response | Promise<Response>,
) {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    if (String(url).endsWith('/events')) {
      if (!init?.signal) throw new Error('O stream precisa de um sinal de cancelamento')
      const stream = new Stream(String(url), init.signal)
      return new Response(stream.corpo, { headers: { 'content-type': 'text/event-stream' } })
    }
    if (String(url).endsWith('/actions') && executar) return executar()
    if (String(url).includes('/jobs?'))
      return new Response(JSON.stringify({ itens: [], total: 0, pagina: 0, tamanho: 100 }))
    return new Response(JSON.stringify(await consultar()), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/jobs/:id', name: 'simulacao', component: SimulateView },
      { path: '/jobs/:id/finalizar', name: 'finalizar', component: { template: '<div />' } },
      { path: '/nova-regra', component: { template: '<div />' } },
    ],
  })
  await router.push('/jobs/job-1')
  const pinia = createPinia()
  const wrapper = mount(SimulateView, {
    global: {
      plugins: [router, pinia],
      stubs: { TheSidebar: true, TheProcessHeader: true, FontAwesomeIcon: true },
    },
  })
  await flushPromises()
  return { wrapper, router, fetchMock, store: usarStoreJobAtual(pinia) }
}

describe('integração da tela com HTTP e SSE', () => {
  it('reconcilia a busca após reconectar e ignora resultado SSE repetido', async () => {
    vi.useFakeTimers()
    let job: Job = jobBuscandoMetaFixture()
    const { wrapper, fetchMock } = await montar(() => job)
    const anterior = Stream.atual
    anterior.desconectar()
    await flushPromises()
    job = jobComMetaFixture()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(Stream.atual).not.toBe(anterior)
    expect(wrapper.text()).toContain('Aceitar meta sugerida')
    const resultado = {
      job_id: job.id,
      simulacao_id: job.simulacao!.id,
      status: 'sucesso',
      veredito: 'viavel',
    }
    Stream.atual.emitir('resultado', resultado)
    await flushPromises()
    const chamadas = fetchMock.mock.calls.length
    Stream.atual.emitir('resultado', resultado)
    await flushPromises()
    expect(fetchMock.mock.calls).toHaveLength(chamadas)
    wrapper.unmount()
  })
  it('permite finalizar sem orçamento, sem aprovação, reprovação ou sugestões', async () => {
    const { wrapper, router } = await montar(jobSemOrcamentoFixture)
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 482.000,00')
    expect(wrapper.text()).not.toMatch(
      /aprovada|reprovada|cabe no seu orçamento|Meta de vendas sugerida/,
    )
    expect(wrapper.find('#titulo-sugestao').exists()).toBe(false)
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Seguir para Finalização')!
      .trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('finalizar')
    wrapper.unmount()
  })

  it('mostra a meta vigente e os três valores da sugestão sem substituir a meta', async () => {
    const job = jobComMetaFixture()
    job.meta_venda = 9999999
    const { wrapper } = await montar(() => job)
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 1.000.000,00')
    expect(wrapper.text()).toContain(
      'A comissão apresentada corresponde à meta de vendas de R$ 1.000.000,00.',
    )
    const valores = wrapper
      .findAll('[aria-labelledby="titulo-meta-sugerida"] dd')
      .map((dd) => dd.text())
    expect(valores).toEqual(['R$ 1.200.000,00', 'R$ 484.500,00', 'R$ 485.000,00'])
    expect(wrapper.text()).not.toMatch(
      /veredito|proposito|job-1|regra-1|tentativa|aguardando_decisao_usuario/,
    )
    wrapper.unmount()
  })

  it('aceita a meta por HTTP uma vez, atualiza a store e o resultado e permite finalizar', async () => {
    let job = jobComMetaFixture()
    const pendente = respostaPendente<Response>()
    const { wrapper, fetchMock, store } = await montar(
      () => job,
      () => pendente.promise,
    )
    const botao = wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button')
    await botao.trigger('click')
    await botao.trigger('click')
    await flushPromises()
    expect(botao.attributes('disabled')).toBeDefined()
    expect(botao.text()).toBe('Aceitando meta...')
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0]![0]).toBe('/api/jobs/job-1/actions')
    expect(JSON.parse(String(posts[0]![1]!.body))).toEqual({ acao: 'aceitar_meta' })
    job = jobMetaAceitaFixture()
    pendente.resolve(new Response(JSON.stringify(job)))
    await flushPromises()
    expect(store.job?.simulacao?.id).toBe('simulacao-meta-aceita')
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 1.200.000,00')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 484.500,00')
    expect(wrapper.find('#titulo-meta-sugerida').exists()).toBe(false)
    expect(wrapper.text()).toContain('Seguir para Finalização')
    wrapper.unmount()
    const reaberta = await montar(() => job)
    expect(reaberta.wrapper.get('#meta').element).toHaveProperty('value', 'R$ 1.200.000,00')
    reaberta.wrapper.unmount()
  })

  it('mantém a sugestão após falha HTTP e permite tentar de novo sem expor o erro bruto', async () => {
    let falhar = true
    let job = jobComMetaFixture()
    const { wrapper } = await montar(
      () => job,
      () =>
        falhar
          ? new Response(
              JSON.stringify({ mensagem: 'segredo: orcamento=485000', codigo: 'estado_invalido' }),
              { status: 500 },
            )
          : new Response(JSON.stringify(jobMetaAceitaFixture())),
    )
    await wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe(
      'Não foi possível concluir a ação. Tente novamente.',
    )
    expect(wrapper.text()).not.toContain('segredo')
    expect(
      wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').attributes('disabled'),
    ).toBeUndefined()
    falhar = false
    job = jobMetaAceitaFixture()
    await wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 1.200.000,00')
    wrapper.unmount()
  })

  it('reconcilia um conflito de aceite e remove a opção já aceita', async () => {
    let job = jobComMetaFixture()
    const { wrapper, store } = await montar(
      () => job,
      () => {
        job = jobMetaAceitaFixture()
        return new Response(
          JSON.stringify({ codigo: 'estado_invalido', mensagem: 'detalhe interno' }),
          {
            status: 409,
            headers: { 'content-type': 'application/json' },
          },
        )
      },
    )
    await wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Confira o resultado atualizado')
    expect(store.job?.simulacao?.id).toBe('simulacao-meta-aceita')
    expect(wrapper.find('#titulo-meta-sugerida').exists()).toBe(false)
    wrapper.unmount()
  })

  it.each(['nao_monotonica', 'intervalo_esgotado', 'falha_execucao'] as const)(
    'explica a ausência de meta maior sem expor %s',
    async (motivo) => {
      const job = jobComMetaFixture()
      job.meta_sugerida = { sem_solucao: { motivo } }
      const { wrapper } = await montar(() => job)
      const secao = wrapper.get('[aria-labelledby="titulo-meta-sugerida"]')
      expect(secao.text()).toContain('Não encontramos uma meta maior')
      expect(secao.findAll('dd')).toHaveLength(0)
      expect(secao.find('button').exists()).toBe(false)
      expect(wrapper.text()).not.toContain(motivo)
      wrapper.unmount()
    },
  )

  it.each(['meta_sugerida', 'sem_solucao', 'busca_meta_encerrada'] as const)(
    'reconcilia %s por SSE durante a busca de meta',
    async (status) => {
      let job: Job = jobBuscandoMetaFixture()
      const { wrapper, fetchMock } = await montar(() => job)
      expect(wrapper.text()).toContain('Buscando uma meta maior')
      expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
      expect(wrapper.text()).not.toContain('Abrir relatório')
      job = jobComMetaFixture()
      if (status === 'sem_solucao')
        job.meta_sugerida = { sem_solucao: { motivo: 'intervalo_esgotado' } }
      if (status === 'busca_meta_encerrada') delete job.meta_sugerida
      const antes = fetchMock.mock.calls.length
      Stream.atual.emitir('etapa', { job_id: 'job-1', etapa: 'sugestao_adaptacao', status })
      await flushPromises()
      expect(fetchMock.mock.calls.length).toBeGreaterThan(antes)
      expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(false)
      expect(wrapper.find('#totalComissionamento').exists()).toBe(true)
      expect(wrapper.find('#titulo-meta-sugerida').exists()).toBe(status !== 'busca_meta_encerrada')
      wrapper.unmount()
    },
  )

  it('oculta o resultado imediatamente ao iniciar busca por SSE, antes da reconsulta', async () => {
    const pendente = respostaPendente<Job>()
    let consultar: () => Job | Promise<Job> = jobFixture
    const { wrapper } = await montar(() => consultar())
    consultar = () => pendente.promise
    Stream.atual.emitir('etapa', {
      job_id: 'job-1',
      etapa: 'sugestao_adaptacao',
      status: 'buscando_meta',
    })
    await flushPromises()
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(true)
    pendente.resolve(jobBuscandoMetaFixture())
    await flushPromises()
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    wrapper.unmount()
  })

  it('mostra somente a taxa que coube e mantém a regra original após várias alternativas', async () => {
    const { wrapper } = await montar(jobComTentativasFixture)
    expect(wrapper.get('#percentual').element).toHaveProperty('value', '2,5%')
    expect(wrapper.get('#percentual-sugestao').element).toHaveProperty('value', '2%')
    expect(wrapper.get('#total-sugestao').element).toHaveProperty('value', 'R$ 480.500,00')
    expect(wrapper.html()).not.toContain('490.000')
    expect(wrapper.text()).not.toMatch(/tentativa|regra-3|simulacao-3/)
    wrapper.unmount()
  })

  it('encerra a busca de taxa pelo SSE sem apresentar os valores das tentativas', async () => {
    let job = jobComTentativasFixture('simulando')
    const { wrapper, router } = await montar(() => job)
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    job = jobComTentativasFixture('simulacao_inviavel')
    Stream.atual.emitir('etapa', {
      job_id: 'job-1',
      etapa: 'sugestao_adaptacao',
      status: 'sem_alternativa',
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Não encontramos uma taxa alternativa que caiba no orçamento.')
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    expect(wrapper.html()).not.toMatch(/480.500|490.000/)
    await wrapper.get('[aria-labelledby="titulo-sugestao"] a').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/nova-regra')
    wrapper.unmount()
  })

  it('cancela a alternativa viável pelo fluxo HTTP existente', async () => {
    const { wrapper, router, fetchMock } = await montar(
      jobComSugestaoFixture,
      () => new Response(JSON.stringify(jobComSugestaoFixture({ status: 'cancelado' }))),
    )
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Cancelar este fluxo.'))!
      .trigger('click')
    await flushPromises()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
    expect(JSON.parse(String(post[1]!.body))).toEqual({ acao: 'cancelar' })
    expect(router.currentRoute.value.path).toBe('/nova-regra')
    wrapper.unmount()
  })

  it.each([200, 409, 500])(
    'registra início, resultado e duração do aceite HTTP %i sem valores ou conteúdo',
    async (status) => {
      const info = vi.spyOn(console, 'info').mockImplementation(() => undefined)
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      let job = jobComMetaFixture()
      const { wrapper } = await montar(
        () => job,
        () => {
          job = jobMetaAceitaFixture()
          return new Response(
            JSON.stringify(
              status === 200 ? job : { codigo: 'estado_invalido', mensagem: 'segredo-interno' },
            ),
            {
              status,
              headers: { 'content-type': 'application/json' },
            },
          )
        },
      )
      await wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').trigger('click')
      await flushPromises()
      const schema = JSON.parse(
        readFileSync(
          resolve(
            dirname(fileURLToPath(import.meta.url)),
            '../../../../../contracts/observability/log.schema.json',
          ),
          'utf8',
        ),
      )
      const registros = [...info.mock.calls, ...warn.mock.calls]
        .map(([linha]) => JSON.parse(String(linha)))
        .filter((r) => r.extra.operacao === 'aceitar_meta')
      expect(registros).toHaveLength(2)
      expect(registros.map((r) => r.extra.resultado)).toEqual([
        'iniciada',
        status === 200 ? 'sucesso' : status === 409 ? 'conflito' : 'falha',
      ])
      for (const registro of registros) {
        expect(Object.keys(registro).sort()).toEqual(
          ['timestamp', 'level', 'message', 'service.name', 'job_id', 'extra'].sort(),
        )
        for (const campo of schema.required) expect(registro).toHaveProperty(campo)
        expect(schema.properties.level.enum).toContain(registro.level)
        expect(schema.properties['service.name'].enum).toContain(registro['service.name'])
        expect(registro['service.name']).toBe('synapse-frontend')
        expect(registro.job_id).toBe('job-1')
        expect(registro.job_id.length).toBeGreaterThanOrEqual(schema.properties.job_id.minLength)
        expect(new Date(registro.timestamp).toISOString()).toBe(registro.timestamp)
        expect(registro.message).toBe('Aceitação de meta no navegador')
        expect(
          Object.keys(registro.extra).every((campo) =>
            ['operacao', 'resultado', 'duracao_ms', 'status_http'].includes(campo),
          ),
        ).toBe(true)
      }
      expect(registros[1].extra.duracao_ms).toBeGreaterThanOrEqual(0)
      expect(JSON.stringify(registros)).not.toMatch(
        /1200000|484500|485000|orcamento|meta_venda|total_simulado|token-da-sessao|segredo-interno|simulacao-meta/,
      )
      wrapper.unmount()
    },
  )

  it('consome regras[] e atualiza o resultado sem recarregar a página', async () => {
    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['Loja mais recente']
    let resposta = jobFixture({ status: 'gerando_regra', regras: [recente, regraFixture()] })
    const { wrapper, fetchMock } = await montar(() => resposta)
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(
      expect.arrayContaining(['/api/jobs/job-1', '/api/jobs/job-1/events']),
    )
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer token-da-sessao')
    }
    expect(Stream.atual.url).toBe('/api/jobs/job-1/events')

    resposta = { ...resposta, status: 'aguardando_decisao_usuario' }
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    Stream.atual.emitir('resultado', {
      job_id: 'job-1',
      simulacao_id: 'simulacao-1',
      status: 'sucesso',
      veredito: 'viavel',
    })
    await flushPromises()
    expect(wrapper.get('#loja').element).toHaveProperty(
      'value',
      'Nome não disponível (código Loja mais recente)',
    )
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 482.000,00')
    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    expect(wrapper.find('#titulo-sugestao').exists()).toBe(false)
    wrapper.unmount()
    expect(Stream.atual.fechado).toBe(true)
  })

  it('explica os limites quando a simulação inviável não tem sugestão, inclusive ao reabrir a página', async () => {
    const resposta = jobFixture({ status: 'simulacao_inviavel', orcamento: 500000 })
    resposta.simulacao!.veredito = 'inviavel'
    resposta.simulacao!.resultado!.totais = {
      baseline: 3299894.24,
      simulado: 3299894.24,
      diferenca_abs: 0,
      diferenca_pct: 0,
      orcamento: 500000,
    }
    const { wrapper, router } = await montar(() => resposta)
    const secao = wrapper.get('[aria-labelledby="titulo-sugestao"]')

    expect(secao.text()).toContain('Não encontramos uma taxa alternativa que caiba no orçamento.')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 3.299.894,24')
    expect(wrapper.get('#percentual').element).toHaveProperty('value', '2,5%')
    expect(wrapper.text()).toContain('Resultado: Regra de negócio reprovada!')
    expect(secao.find('#total-sugestao').exists()).toBe(false)
    expect(secao.text()).not.toContain('Seguir para a próxima etapa.')

    await secao.get('a').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/nova-regra')
    wrapper.unmount()

    const reaberta = await montar(() => resposta)
    expect(reaberta.wrapper.text()).toContain(
      'Não encontramos uma taxa alternativa que caiba no orçamento.',
    )
    reaberta.wrapper.unmount()
  })

  it('substitui o aviso pela alternativa quando ela chega pelo SSE', async () => {
    const alternativa = jobComSugestaoFixture()
    let resposta = jobFixture({
      status: 'simulacao_inviavel',
      simulacao: alternativa.simulacoes![0],
    })
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Não encontramos uma taxa alternativa que caiba no orçamento.')

    resposta = jobComSugestaoFixture({ status: 'gerando_regra', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    await flushPromises()

    expect(wrapper.text()).not.toContain(
      'Não encontramos uma taxa alternativa que caiba no orçamento.',
    )
    expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(true)
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)

    resposta = alternativa
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    await flushPromises()
    expect(wrapper.text()).toContain('Seguir para a próxima etapa.')
    expect(wrapper.text()).not.toContain(
      'Não encontramos uma taxa alternativa que caiba no orçamento.',
    )
    wrapper.unmount()
  })

  it('exibe os dois resultados e aceita a alternativa sem solicitar outra simulação', async () => {
    const job = jobComSugestaoFixture({ meta_venda: 30000000, orcamento: 2500000 })
    job.simulacoes![0]!.meta_venda = 1000000
    job.simulacoes![1]!.meta_venda = 1100000
    job.simulacoes![1]!.resultado!.totais!.orcamento = 486000
    const { wrapper, router, fetchMock } = await montar(() => job)
    expect(wrapper.get('label[for="meta"]').text()).toBe('Meta de vendas')
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 1.000.000,00')
    expect(wrapper.get('label[for="meta-sugestao"]').text()).toBe('Meta de vendas')
    expect(wrapper.get('#meta-sugestao').element).toHaveProperty('value', 'R$ 1.100.000,00')
    expect(wrapper.get('label[for="orcamento"]').text()).toBe('Orçamento de comissão')
    expect(wrapper.get('#orcamento').element).toHaveProperty('value', 'R$ 485.000,00')
    expect(wrapper.get('label[for="orcamento-sugestao"]').text()).toBe('Orçamento de comissão')
    expect(wrapper.get('#orcamento-sugestao').element).toHaveProperty('value', 'R$ 486.000,00')
    expect(wrapper.get('#percentual').element).toHaveProperty('value', '2,5%')
    expect(wrapper.get('[data-testid="percentual-sugestao"]').element).toHaveProperty(
      'value',
      '2,46%',
    )
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')
    expect(wrapper.get('#total-sugestao').element).toHaveProperty('value', 'R$ 484.226,40')
    expect(wrapper.text()).toContain('A regra de negócio NÃO cabe no seu orçamento.')
    expect(wrapper.text()).toContain('A sugestão cabe no seu orçamento.')
    await wrapper
      .findAll('button')
      .find((botao) => botao.text().includes('Seguir para a próxima etapa.'))!
      .trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('finalizar')
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    wrapper.unmount()
  })

  it('acompanha a simulação da alternativa pelo SSE sem resultados intermediários', async () => {
    let resposta = jobComSugestaoFixture({ status: 'simulando', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(true)
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    resposta = jobComSugestaoFixture()
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    await flushPromises()
    expect(wrapper.get('#total-sugestao').element).toHaveProperty('value', 'R$ 484.226,40')
    expect(wrapper.find('[data-testid="carregando-sugestao"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Seguir para a próxima etapa.')
    wrapper.unmount()
  })

  it('mostra o erro da alternativa imediatamente enquanto a consulta atualizada está pendente', async () => {
    const pendente = respostaPendente<Job>()
    let consultar: () => Job | Promise<Job> = () => jobComSugestaoFixture()
    const { wrapper } = await montar(() => consultar())
    consultar = () => pendente.promise

    Stream.atual.emitir('estado', { job_id: 'job-1', status: 'erro' })
    await flushPromises()

    expect(wrapper.text()).toContain('Não foi possível concluir a simulação da alternativa.')
    expect(wrapper.text()).not.toContain('Seguir para a próxima etapa.')
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')
    pendente.resolve(jobComSugestaoFixture({ status: 'erro' }))
    await flushPromises()
    wrapper.unmount()
  })

  it('mostra o progresso de preparação sem expor resultados', async () => {
    const resposta = jobComSugestaoFixture({ status: 'gerando_regra', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    const { wrapper } = await montar(() => resposta)

    expect(wrapper.find('[aria-label="Processando simulação"]').exists()).toBe(true)
    expect(wrapper.find('#totalComissionamento').exists()).toBe(false)
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    wrapper.unmount()
  })

  it('explica o fim da busca sem mostrar a alternativa inviável', async () => {
    const resposta = jobComSugestaoFixture({ status: 'simulacao_inviavel' })
    resposta.simulacoes![1]!.veredito = 'inviavel'
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Não encontramos uma taxa alternativa que caiba no orçamento.')
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Seguir para a próxima etapa.')
    expect(wrapper.text()).toContain('Iniciar nova regra')
    wrapper.unmount()
  })

  it('explicita falha da alternativa e conserva o resultado original', async () => {
    const resposta = jobComSugestaoFixture({ status: 'erro' })
    resposta.simulacoes![1]!.status = 'erro_codigo'
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Não foi possível concluir a simulação da alternativa.')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    wrapper.unmount()
  })
})
