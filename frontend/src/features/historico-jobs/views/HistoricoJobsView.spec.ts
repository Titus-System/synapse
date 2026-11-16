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
function resposta(itens: JobResumo[], total = itens.length, pagina = 0): PaginaJobs {
  return { itens, pagina, tamanho: 5, total }
}
function servir(itens: JobResumo[], total = itens.length) {
  vi.mocked(apiClient.listarJobs).mockImplementation(async (parametros = {}) =>
    parametros.situacao === (rota.atual.name === 'regras-arquivadas' ? 'arquivadas' : 'salvas')
      ? resposta(itens, total, parametros.pagina)
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
        { situacao, pagina: 0, tamanho: 5 },
        expect.any(AbortSignal),
      )
      expect(apiClient.listarJobs).toHaveBeenCalledTimes(2)
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
        : resposta(
            p.pagina === 1 ? [resumo(6), resumo(7)] : [1, 2, 3, 4, 5].map((n) => resumo(n)),
            7,
            p.pagina,
          ),
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
      return resposta([resumo(1)], 12)
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
