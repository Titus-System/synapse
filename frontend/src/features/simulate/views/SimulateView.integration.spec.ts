import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import {
  jobFixture,
  regraFixture,
  jobComSugestaoFixture,
  respostaPendente,
} from '@/services/job.fixtures'
import type { Job } from '@/types/api'
import SimulateView from './SimulateView.vue'

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
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function montar(consultar: () => Job | Promise<Job>) {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
    if (String(url).endsWith('/events')) {
      if (!init?.signal) throw new Error('O stream precisa de um sinal de cancelamento')
      const stream = new Stream(String(url), init.signal)
      return new Response(stream.corpo, { headers: { 'content-type': 'text/event-stream' } })
    }
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
  const wrapper = mount(SimulateView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { TheSidebar: true, TheProcessHeader: true, FontAwesomeIcon: true },
    },
  })
  await flushPromises()
  return { wrapper, router, fetchMock }
}

function comMetaSugerida(): Job {
  const job = jobFixture({
    meta_venda: 30000000,
    orcamento: 2500000,
    meta_sugerida: { meta_venda: 60000000, total_simulado: 2400000, orcamento: 2500000 },
  })
  job.simulacao!.meta_venda = 30000000
  job.simulacao!.resultado!.totais!.simulado = 1200000
  job.simulacao!.resultado!.totais!.orcamento = 2500000
  return job
}

describe('integração da tela com HTTP e SSE', () => {
  it('mostra a meta já encontrada ao reabrir e só troca o resultado após a aceitação', async () => {
    let resposta = comMetaSugerida()
    const { wrapper, fetchMock } = await montar(() => resposta)
    const secao = wrapper.get('[aria-labelledby="titulo-meta-sugerida"]')
    expect(secao.text()).toContain('R$ 60.000.000,00')
    expect(secao.text()).toContain('R$ 2.400.000,00')
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 30.000.000,00')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 1.200.000,00')
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)

    resposta = comMetaSugerida()
    delete resposta.meta_sugerida
    resposta.simulacao!.meta_venda = 60000000
    resposta.simulacao!.resultado!.totais!.simulado = 2400000
    await secao.get('button').trigger('click')
    await flushPromises()
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0]![0]).toBe('/api/jobs/job-1/actions')
    expect(JSON.parse(String(posts[0]![1]!.body))).toEqual({ acao: 'aceitar_meta' })
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 60.000.000,00')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 2.400.000,00')
    expect(wrapper.find('#titulo-meta-sugerida').exists()).toBe(false)
    wrapper.unmount()
  })

  it('acompanha início e conclusão da busca pelo SSE sem apagar o resultado aprovado', async () => {
    let resposta: Job & { busca_meta_em_curso?: true } = comMetaSugerida()
    delete resposta.meta_sugerida
    const { wrapper, fetchMock } = await montar(() => resposta)
    expect(wrapper.find('#titulo-meta-sugerida').exists()).toBe(false)
    resposta = { ...resposta, busca_meta_em_curso: true }
    Stream.atual.emitir('etapa', {
      job_id: 'job-1',
      etapa: 'sugestao_adaptacao',
      status: 'buscando_meta',
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Estamos buscando uma meta de vendas maior')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 1.200.000,00')
    resposta = comMetaSugerida()
    Stream.atual.emitir('etapa', {
      job_id: 'job-1',
      etapa: 'sugestao_adaptacao',
      status: 'meta_sugerida',
    })
    await flushPromises()
    expect(wrapper.get('[aria-labelledby="titulo-meta-sugerida"]').text()).toContain(
      'R$ 60.000.000,00',
    )
    expect(wrapper.text()).not.toContain('Estamos buscando uma meta de vendas maior')
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    wrapper.unmount()
  })

  it.each(['nao_monotonica', 'intervalo_esgotado', 'falha_execucao'] as const)(
    'informa o término %s da busca e preserva a possibilidade de finalizar a meta atual',
    async (motivo) => {
      const resposta = comMetaSugerida()
      resposta.meta_sugerida = { sem_solucao: { motivo } }
      const { wrapper } = await montar(() => resposta)
      expect(wrapper.text()).toContain('A busca automática não confirmou uma meta de vendas maior.')
      expect(wrapper.findAll('button').some((item) => item.text() === 'Usar meta sugerida')).toBe(
        false,
      )
      expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 30.000.000,00')
      expect(wrapper.text()).toContain('Seguir para Finalização')
      wrapper.unmount()
    },
  )

  it('mantém a simulação aprovada visível quando a aceitação da meta é recusada', async () => {
    const { wrapper, fetchMock } = await montar(() => comMetaSugerida())
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ codigo: 'estado_invalido', mensagem: 'SEGREDO-INTERNO' }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      }),
    )
    await wrapper.get('[aria-labelledby="titulo-meta-sugerida"] button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[aria-labelledby="titulo-meta-sugerida"] [role="alert"]').text()).toContain(
      'Esta ação não está disponível',
    )
    expect(wrapper.text()).not.toContain('SEGREDO-INTERNO')
    expect(wrapper.get('#meta').element).toHaveProperty('value', 'R$ 30.000.000,00')
    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    wrapper.unmount()
  })

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

    expect(secao.text()).toContain('Nenhuma sugestão disponível no momento.')
    expect(secao.text()).toContain(
      'A busca automática reduz todas as taxas de comissão da regra na mesma proporção, mantém as demais condições e testa até três alternativas.',
    )
    expect(secao.text()).toContain(
      'Ela não altera as comissões que a regra não alcança, como as de lojas, marcas e cargos fora dela, nem valores fixos, como bônus.',
    )
    expect(secao.text()).toContain('Nem sempre encontra uma alternativa viável.')
    expect(secao.text()).not.toContain('revisão manual')
    expect(secao.find('[data-testid="motivo-sugestao"]').exists()).toBe(false)
    expect(secao.text()).toContain(
      'Isso não significa que seja impossível encontrar uma regra que caiba no orçamento.',
    )
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
    expect(reaberta.wrapper.text()).toContain('Nenhuma sugestão disponível no momento.')
    reaberta.wrapper.unmount()
  })

  it('mostra o motivo que a api informa quando a busca termina sem alternativa', async () => {
    const motivo =
      'O orçamento de R$ 500.000,00 é menor que as comissões das lojas fora da regra (R$ 550.000,00), que a sugestão não altera.'
    const resposta = jobFixture({ status: 'simulacao_inviavel', orcamento: 500000, motivo })
    resposta.simulacao!.veredito = 'inviavel'
    const { wrapper } = await montar(() => resposta)

    const secao = wrapper.get('[aria-labelledby="titulo-sugestao"]')
    expect(secao.get('[data-testid="motivo-sugestao"]').text()).toBe(motivo)
    expect(secao.text()).not.toContain('Isso não significa que seja impossível')
    wrapper.unmount()
  })

  it('substitui o aviso pela alternativa quando ela chega pelo SSE', async () => {
    const alternativa = jobComSugestaoFixture()
    let resposta = jobFixture({
      status: 'simulacao_inviavel',
      simulacao: alternativa.simulacoes![0],
    })
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Nenhuma sugestão disponível no momento.')

    resposta = jobComSugestaoFixture({ status: 'gerando_regra', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    await flushPromises()

    expect(wrapper.text()).not.toContain('Nenhuma sugestão disponível no momento.')
    expect(wrapper.text()).toContain('Estamos preparando a regra alternativa para a simulação.')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')

    resposta = alternativa
    Stream.atual.emitir('estado', { job_id: 'job-1', status: resposta.status })
    await flushPromises()
    expect(wrapper.text()).toContain('Seguir para a próxima etapa.')
    expect(wrapper.text()).not.toContain('Nenhuma sugestão disponível no momento.')
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
    expect(wrapper.text()).toContain(
      'As taxas foram reduzidas na mesma proporção; as demais condições da regra foram mantidas.',
    )
    await wrapper
      .findAll('button')
      .find((botao) => botao.text().includes('Seguir para a próxima etapa.'))!
      .trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('finalizar')
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
    wrapper.unmount()
  })

  it('acompanha a simulação da alternativa pelo SSE preservando o resultado original', async () => {
    let resposta = jobComSugestaoFixture({ status: 'simulando', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('Estamos simulando uma alternativa')
    expect(wrapper.find('[data-testid="carregando-sugestao"]').exists()).toBe(true)
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')
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

  it('mostra o progresso de preparação dentro da sugestão sem ocultar o original', async () => {
    const resposta = jobComSugestaoFixture({ status: 'gerando_regra', simulacao: null })
    resposta.simulacoes = resposta.simulacoes!.slice(0, 1)
    const { wrapper } = await montar(() => resposta)

    expect(wrapper.text()).toContain('Estamos preparando a regra alternativa para a simulação.')
    expect(wrapper.get('#totalComissionamento').element).toHaveProperty('value', 'R$ 492.100,00')
    expect(wrapper.find('#total-sugestao').exists()).toBe(false)
    wrapper.unmount()
  })

  it('mostra a alternativa inviável sem permitir sua aceitação', async () => {
    const resposta = jobComSugestaoFixture({ status: 'simulacao_inviavel' })
    resposta.simulacoes![1]!.veredito = 'inviavel'
    const { wrapper } = await montar(() => resposta)
    expect(wrapper.text()).toContain('A alternativa ainda excede o orçamento.')
    expect(wrapper.find('[data-testid="motivo-sugestao"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Seguir para a próxima etapa.')
    expect(wrapper.text()).toContain('Cancelar este fluxo.')
    wrapper.unmount()
  })

  it('explica por que a alternativa inviável é o fim da busca com o motivo da api', async () => {
    const motivo = 'O orçamento de R$ 485.000,00 é menor que as comissões das lojas fora da regra.'
    const resposta = jobComSugestaoFixture({ status: 'simulacao_inviavel', motivo })
    resposta.simulacoes![1]!.veredito = 'inviavel'
    const { wrapper } = await montar(() => resposta)

    expect(wrapper.get('[data-testid="motivo-sugestao"]').text()).toBe(motivo)
    expect(wrapper.text()).toContain('A alternativa ainda excede o orçamento.')
    expect(wrapper.text()).not.toContain('não se preocupe')
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
