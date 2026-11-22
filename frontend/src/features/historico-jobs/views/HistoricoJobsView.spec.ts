import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { reactive } from 'vue'
import { createPinia } from 'pinia'
import { apiClient } from '@/services/api'
import { jobFixture, regraFixture } from '@/services/job.fixtures'
import type { JobResumo, PaginaJobs } from '@/types/api'
import HistoricoJobsView from './HistoricoJobsView.vue'

const { rota, roteador } = vi.hoisted(() => ({
  rota: { atual: { name: 'regras-salvas' } },
  roteador: { push: vi.fn<(destino: unknown) => void>() },
}))
vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
  },
}))
vi.mock('vue-router', () => ({ useRoute: () => rota.atual, useRouter: () => roteador }))
let wrapper: VueWrapper | undefined
let avisos: { mock: { calls: unknown[][] } }
const idDe = (n: number) => `019a1e43-7a00-7c3b-9d41-8f2c6a1b7e0${n}`
const resumo = (n: number, status: JobResumo['status'] = 'liberado'): JobResumo => ({
  id: idDe(n),
  nome: `Comissão da loja ${n}`,
  status,
  competencias: ['2025-11'],
  criado_em: '2026-10-28T16:40:00Z',
})
function resposta(itens: JobResumo[], total = itens.length, pagina = 0, tamanho = 100): PaginaJobs {
  return { itens, pagina, tamanho, total }
}
function servir(itens: JobResumo[], total = itens.length) {
  vi.mocked(apiClient.listarJobs).mockImplementation(
    async ({ situacao, pagina = 0, tamanho = 100 } = {}) =>
      situacao === (rota.atual.name === 'regras-arquivadas' ? 'arquivadas' : 'salvas')
        ? resposta(itens.slice(pagina * tamanho, (pagina + 1) * tamanho), total, pagina, tamanho)
        : resposta([], 23),
  )
}
function montar() {
  wrapper = mount(HistoricoJobsView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
      },
    },
  })
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  rota.atual = reactive({ name: 'regras-salvas' })
  avisos = vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.mocked(apiClient.consultarJob).mockImplementation(async (id) => jobFixture({ id }))
  servir([])
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('repositório paginado', () => {
  it.each(['salvas', 'arquivadas'] as const)(
    'carrega %s com filtro e totais da API',
    async (situacao) => {
      rota.atual.name = `regras-${situacao}`
      servir([resumo(1, situacao === 'salvas' ? 'liberado' : 'arquivado')], 14)
      const tela = montar()
      await flushPromises()
      expect(apiClient.listarJobs).toHaveBeenCalledWith(
        { situacao, pagina: 0, tamanho: 100 },
        expect.any(AbortSignal),
      )
      expect(apiClient.consultarJob).toHaveBeenCalledTimes(1)
      expect(tela.get('main').text()).toContain('Total: 14 regras registradas')
      expect(tela.get('aside').text()).toContain('Total Catalogado14')
      expect(tela.get('aside').find('a[href="/arquivadas"]').exists()).toBe(false)
      expect(tela.get('aside').text()).not.toContain('Recentes')
      expect(tela.get('article').text()).not.toMatch(
        /Liberado|Arquivado|Processamento|019a1e43|versão/,
      )
      expect(tela.find('button[aria-label^="Reprocessar"]').exists()).toBe(
        situacao === 'arquivadas',
      )
    },
  )

  it.each(['salvas', 'arquivadas'])('mostra carregamento de %s', async (situacao) => {
    rota.atual.name = `regras-${situacao}`
    vi.mocked(apiClient.listarJobs).mockReturnValue(new Promise(() => {}))
    const tela = montar()
    expect(tela.get('[aria-busy="true"]').text()).toContain('Carregando regras')
    expect(tela.find('article').exists()).toBe(false)
  })

  it.each(['salvas', 'arquivadas'])('mostra vazio em %s', async (situacao) => {
    rota.atual.name = `regras-${situacao}`
    const tela = montar()
    await flushPromises()
    expect(tela.text()).toContain(
      `Nenhuma regra ${situacao === 'salvas' ? 'salva' : 'arquivada'} ainda`,
    )
    expect(apiClient.consultarJob).not.toHaveBeenCalled()
  })

  it.each(['salvas', 'arquivadas'])(
    'trata falha de %s, sanitiza log e permite tentar novamente',
    async (situacao) => {
      rota.atual.name = `regras-${situacao}`
      vi.mocked(apiClient.listarJobs).mockRejectedValue(new Error('token e regra privados'))
      const tela = montar()
      await flushPromises()
      expect(tela.get('main [role="alert"]').text()).toContain(
        'Não foi possível carregar as regras',
      )
      expect(tela.text()).not.toContain('token e regra privados')
      expect(avisos).toHaveBeenCalled()
      const eventos = avisos.mock.calls.map((args) => JSON.parse(args[0] as string))
      expect(eventos).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            'service.name': 'synapse-frontend',
            level: 'WARN',
            extra: expect.objectContaining({
              operacao: `listar_regras_${situacao}`,
              resultado: 'falha',
            }),
          }),
        ]),
      )
      expect(JSON.stringify(eventos)).not.toContain('token e regra privados')
      servir([resumo(1)])
      await tela.get('main [role="alert"] button').trigger('click')
      await flushPromises()
      expect(tela.findAll('article')).toHaveLength(1)
    },
  )

  it('consulta só os detalhes da nova página e usa o total filtrado', async () => {
    vi.mocked(apiClient.listarJobs).mockImplementation(async (p = {}) =>
      p.situacao === 'arquivadas'
        ? resposta([], 80)
        : resposta([1, 2, 3, 4, 5, 6, 7].map((n) => resumo(n))),
    )
    const tela = montar()
    await flushPromises()
    expect(apiClient.consultarJob).toHaveBeenCalledTimes(5)
    vi.mocked(apiClient.consultarJob).mockClear()
    await tela.get('button[aria-label="Próxima página"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(apiClient.consultarJob).mock.calls.map((args) => args[0])).toEqual([
      idDe(6),
      idDe(7),
    ])
    expect(tela.get('main').text()).toContain('Mostrando 6–7 de 7')
    expect(tela.get('button[aria-label="Próxima página"]').attributes('disabled')).toBeDefined()
    expect(tela.get('aside').text()).toContain('Total Catalogado7')
  })

  it('mantém os demais cartões quando um detalhe falha', async () => {
    servir([resumo(1), resumo(2)])
    vi.mocked(apiClient.consultarJob)
      .mockRejectedValueOnce(new Error('texto privado'))
      .mockResolvedValueOnce(jobFixture({ nome: 'Regra carregada' }))
    const tela = montar()
    await flushPromises()
    expect(tela.findAll('article')).toHaveLength(2)
    expect(tela.findAll('article [role="alert"]')).toHaveLength(1)
    expect(tela.text()).toContain('Regra carregada')
    expect(avisos.mock.calls.map((args) => JSON.parse(args[0] as string))).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          job_id: idDe(1),
          extra: expect.objectContaining({ operacao: 'consultar_regra_historico' }),
        }),
      ]),
    )
  })

  it('falha na contagem da outra lista não impede os cartões', async () => {
    vi.mocked(apiClient.listarJobs).mockImplementation(async (p = {}) => {
      if (p.situacao === 'arquivadas') throw new Error('falha')
      return resposta(p.pagina ? [] : [resumo(1)], 12, p.pagina)
    })
    const tela = montar()
    await flushPromises()
    expect(tela.findAll('article')).toHaveLength(1)
    expect(tela.get('aside').text()).toContain('Total Catalogado12')
  })

  it('leva Detalhes ao cartão finalizado e Reprocessar à entrada pelo roteador', async () => {
    rota.atual.name = 'regras-arquivadas'
    servir([resumo(1, 'arquivado')])
    const tela = montar()
    await flushPromises()
    await tela.get('button[aria-label^="Detalhes de"]').trigger('click')
    expect(roteador.push).toHaveBeenCalledWith({ name: 'finalizar', params: { id: idDe(1) } })
    await tela.get('button[aria-label^="Reprocessar"]').trigger('click')
    expect(roteador.push).toHaveBeenCalledWith({
      name: 'nova-regra',
      query: { reprocessar: idDe(1) },
    })
  })

  it('transforma só a versão mais recente sem exibir identificadores', async () => {
    const antiga = regraFixture(1)
    const recente = regraFixture(2)
    antiga.representacao.nucleo.loja = ['antiga']
    recente.representacao.nucleo.loja = ['atual']
    servir([resumo(1)])
    vi.mocked(apiClient.consultarJob).mockResolvedValue(
      jobFixture({ regras: [recente, antiga], nome: 'Comissão' }),
    )
    const tela = montar()
    await flushPromises()
    expect(tela.get('article h2').attributes('title')).toContain('atual')
    expect(tela.get('article h2').attributes('title')).not.toContain('antiga')
    expect(tela.get('article').text()).not.toContain(idDe(1))
  })

  it('numera a regra pelos 6 últimos caracteres do id e omite o nome ausente', async () => {
    servir([resumo(1), { ...resumo(2), nome: null }])
    const tela = montar()
    await flushPromises()
    expect(tela.findAll('article h2').map((titulo) => titulo.text())).toEqual([
      'Regra 1B7E01 · Comissão da loja 1',
      'Regra 1B7E02',
    ])
    expect(tela.find('button[aria-label="Detalhes de Regra 1B7E02"]').exists()).toBe(true)
  })

  it('cancela a página anterior quando a rota muda e ignora resposta atrasada', async () => {
    let resolver: (p: PaginaJobs) => void = () => {}
    vi.mocked(apiClient.listarJobs)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolver = resolve
          }),
      )
      .mockResolvedValue(resposta([], 0))
    const tela = montar()
    const signal = vi.mocked(apiClient.listarJobs).mock.calls[0]?.[1]
    rota.atual.name = 'regras-arquivadas'
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    resolver(resposta([resumo(99)]))
    await flushPromises()
    expect(tela.get('h1').text()).toContain('Arquivadas')
    expect(tela.findAll('article')).toHaveLength(0)
    expect(apiClient.consultarJob).not.toHaveBeenCalled()
  })
})

describe('busca, ordenação e filtros', () => {
  const titulos = (tela: VueWrapper) => tela.findAll('article h2').map((titulo) => titulo.text())

  it('pesquisa pelo nome sem diferenciar acento nem caixa', async () => {
    servir([resumo(1), { ...resumo(2), nome: 'Bônus trimestral' }, resumo(3)])
    vi.mocked(apiClient.consultarJob).mockImplementation(async (id) =>
      jobFixture({ id, nome: id === idDe(2) ? 'Bônus trimestral' : `Comissão ${id.slice(-1)}` }),
    )
    const tela = montar()
    await flushPromises()
    await tela.get('input[type="search"]').setValue('BONUS')
    await flushPromises()
    expect(titulos(tela)).toEqual(['Regra 1B7E02 · Bônus trimestral'])
    expect(tela.get('main').text()).toContain('Mostrando 1–1 de 1 regras encontradas')
    expect(tela.get('main').text()).toContain('Total: 3 regras registradas')
  })

  it('pesquisa na lógica consultando também as regras fora da página', async () => {
    servir([1, 2, 3, 4, 5, 6, 7].map((n) => resumo(n)))
    vi.mocked(apiClient.consultarJob).mockImplementation(async (id) => {
      const regra = regraFixture(1)
      regra.representacao.nucleo.loja = [id === idDe(7) ? 'joinville' : 'outra']
      return jobFixture({ id, regras: [regra], nome: `Comissão ${id.slice(-1)}` })
    })
    const tela = montar()
    await flushPromises()
    expect(apiClient.consultarJob).toHaveBeenCalledTimes(5)
    await tela.get('input[type="search"]').setValue('Joinville')
    expect(tela.text()).toContain('Buscando também na lógica das regras')
    await flushPromises()
    expect(apiClient.consultarJob).toHaveBeenCalledTimes(7)
    expect(titulos(tela)).toEqual(['Regra 1B7E07 · Comissão 7'])
    expect(tela.text()).not.toContain('Buscando também na lógica das regras')
  })

  it('mostra vazio filtrado e limpa a pesquisa', async () => {
    servir([resumo(1), resumo(2)])
    const tela = montar()
    await flushPromises()
    await tela.get('input[type="search"]').setValue('inexistente')
    await flushPromises()
    expect(tela.text()).toContain('Nenhuma regra encontrada')
    expect(tela.text()).not.toContain('Nenhuma regra salva ainda')
    await tela.get('main [role="status"] button').trigger('click')
    await flushPromises()
    expect(tela.findAll('article')).toHaveLength(2)
    expect((tela.get('input[type="search"]').element as HTMLInputElement).value).toBe('')
  })

  it('ordena por data e por nome', async () => {
    servir([
      { ...resumo(1), nome: 'Bravo', criado_em: '2026-10-02T10:00:00Z' },
      { ...resumo(2), nome: 'alfa', criado_em: '2026-10-03T10:00:00Z' },
      { ...resumo(3), nome: null, criado_em: '2026-10-01T10:00:00Z' },
    ])
    vi.mocked(apiClient.consultarJob).mockImplementation(async (id) =>
      jobFixture({ id, nome: { [idDe(1)]: 'Bravo', [idDe(2)]: 'alfa' }[id] ?? null }),
    )
    const tela = montar()
    await flushPromises()
    expect(titulos(tela)).toEqual(['Regra 1B7E02 · alfa', 'Regra 1B7E01 · Bravo', 'Regra 1B7E03'])
    await tela.get('select[aria-label="Ordenação"]').setValue('antigas')
    expect(titulos(tela)).toEqual(['Regra 1B7E03', 'Regra 1B7E01 · Bravo', 'Regra 1B7E02 · alfa'])
    await tela.get('select[aria-label="Ordenação"]').setValue('nome-asc')
    expect(titulos(tela)).toEqual(['Regra 1B7E02 · alfa', 'Regra 1B7E01 · Bravo', 'Regra 1B7E03'])
    await tela.get('select[aria-label="Ordenação"]').setValue('nome-desc')
    expect(titulos(tela)).toEqual(['Regra 1B7E01 · Bravo', 'Regra 1B7E02 · alfa', 'Regra 1B7E03'])
  })

  it('filtra pelo período a partir da data atual', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-22T12:00:00Z'))
    try {
      servir([
        { ...resumo(1), criado_em: '2026-11-20T10:00:00Z' },
        { ...resumo(2), criado_em: '2026-10-10T10:00:00Z' },
        { ...resumo(3), criado_em: '2025-06-10T10:00:00Z' },
      ])
      const tela = montar()
      await flushPromises()
      await tela.get('select[aria-label="Período"]').setValue('7d')
      expect(tela.findAll('article')).toHaveLength(1)
      await tela.get('select[aria-label="Período"]').setValue('90d')
      expect(tela.findAll('article')).toHaveLength(2)
      await tela.get('select[aria-label="Período"]').setValue('12m')
      expect(tela.findAll('article')).toHaveLength(2)
      await tela.get('select[aria-label="Período"]').setValue('todos')
      expect(tela.findAll('article')).toHaveLength(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('aplica meses simulados e datas dos filtros avançados', async () => {
    servir([
      { ...resumo(1), competencias: ['2025-08'], criado_em: '2026-10-20T10:00:00Z' },
      { ...resumo(2), competencias: ['2025-11'], criado_em: '2026-10-05T10:00:00Z' },
      { ...resumo(3), competencias: ['2025-08', '2025-09'], criado_em: '2026-09-01T10:00:00Z' },
    ])
    const tela = montar()
    await flushPromises()
    const botao = tela.get('button[aria-controls="filtros-avancados"]')
    expect(botao.attributes('aria-expanded')).toBe('false')
    await botao.trigger('click')
    expect(botao.attributes('aria-expanded')).toBe('true')
    const painel = tela.get('#filtros-avancados')
    expect(painel.findAll('label').map((rotulo) => rotulo.text())).toEqual(
      expect.arrayContaining(['11/2025', '09/2025', '08/2025']),
    )
    const agosto = painel
      .findAll('label')
      .find((rotulo) => rotulo.text() === '08/2025')!
      .get('input')
    await agosto.setValue(true)
    expect(titulos(tela).map((titulo) => titulo.slice(0, 12))).toEqual([
      'Regra 1B7E01',
      'Regra 1B7E03',
    ])
    expect(botao.text()).toContain('1')
    await painel.findAll('input[type="date"]')[1]!.setValue('2026-10-19')
    expect(titulos(tela).map((titulo) => titulo.slice(0, 12))).toEqual(['Regra 1B7E03'])
    await painel.findAll('input[type="date"]')[0]!.setValue('2026-09-02')
    expect(tela.text()).toContain('Nenhuma regra encontrada')
    await painel
      .findAll('button')
      .find((b) => b.text() === 'Limpar filtros')!
      .trigger('click')
    expect(tela.findAll('article')).toHaveLength(3)
    expect(botao.text()).not.toMatch(/\d/)
  })

  it('volta à primeira página quando um filtro muda', async () => {
    servir([1, 2, 3, 4, 5, 6, 7].map((n) => resumo(n)))
    const tela = montar()
    await flushPromises()
    await tela.get('button[aria-label="Próxima página"]').trigger('click')
    await flushPromises()
    expect(tela.get('main').text()).toContain('Mostrando 6–7 de 7')
    await tela.get('select[aria-label="Ordenação"]').setValue('antigas')
    expect(tela.get('main').text()).toContain('Mostrando 1–5 de 7')
  })

  it('volta aos filtros iniciais ao trocar de lista', async () => {
    servir([resumo(1)])
    const tela = montar()
    await flushPromises()
    await tela.get('input[type="search"]').setValue('inexistente')
    rota.atual.name = 'regras-arquivadas'
    servir([resumo(2, 'arquivado')])
    await flushPromises()
    expect((tela.get('input[type="search"]').element as HTMLInputElement).value).toBe('')
    expect(tela.findAll('article')).toHaveLength(1)
  })
})
