import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { usarStoreRenomearRegra } from '@/stores/renomearRegra'
import type { JobResumo, PaginaJobs } from '@/types/api'
import TheSidebar from './TheSidebar.vue'

vi.mock('@/services/api', () => ({
  apiClient: {
    renomearJob: vi.fn<typeof apiClient.renomearJob>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
  },
}))

vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))

// Faz o papel do navegador: avisa quando o fim da lista aparece e, como o observador real,
// avisa logo ao observar se ele já está visível.
class ObservadorControlavel {
  static atual: ObservadorControlavel | null = null
  static fimVisivel = false
  readonly alvos = new Set<Element>()

  constructor(
    readonly callback: IntersectionObserverCallback,
    readonly opcoes: IntersectionObserverInit = {},
  ) {
    ObservadorControlavel.atual = this
  }

  observe(alvo: Element) {
    this.alvos.add(alvo)
    if (ObservadorControlavel.fimVisivel) setTimeout(() => this.avisar(alvo))
  }

  unobserve(alvo: Element) {
    this.alvos.delete(alvo)
  }

  disconnect() {
    this.alvos.clear()
  }

  takeRecords() {
    return []
  }

  mostrarFimDaLista() {
    for (const alvo of this.alvos) this.avisar(alvo)
  }

  private avisar(alvo: Element) {
    if (!this.alvos.has(alvo)) return
    this.callback(
      [{ isIntersecting: true, target: alvo } as unknown as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    )
  }
}

function resumo(numero: number, nome?: string): JobResumo {
  return {
    id: `job-${numero}`,
    nome: nome ?? `Regra ${numero}`,
    status: 'liberado',
    competencias: [],
    criado_em: '2026-09-19T12:00:00Z',
  }
}

function criarJobs(quantidade: number): JobResumo[] {
  return Array.from({ length: quantidade }, (_, indice) => resumo(indice + 1))
}

function servir(jobs: JobResumo[]) {
  vi.mocked(apiClient.listarJobs).mockImplementation(async ({ pagina = 0, tamanho = 20 } = {}) => ({
    itens: jobs.slice(pagina * tamanho, pagina * tamanho + tamanho),
    pagina,
    tamanho,
    total: jobs.length,
  }))
}

function opcoesDeMontagem() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return {
    global: {
      plugins: [pinia],
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
      },
    },
  }
}

async function montar(props: Record<string, unknown> = {}) {
  const conteiner = mount(TheSidebar, { ...opcoesDeMontagem(), props, attachTo: document.body })
  await flushPromises()
  return conteiner
}

function linksDeRegras(conteiner: Awaited<ReturnType<typeof montar>>) {
  return conteiner.findAll('ul a[href^="/jobs/"]')
}

beforeEach(() => {
  vi.resetAllMocks()
  ObservadorControlavel.atual = null
  ObservadorControlavel.fimVisivel = false
  vi.stubGlobal('IntersectionObserver', ObservadorControlavel)
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
})

afterEach(() => {
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('TheSidebar', () => {
  it('apresenta as regras carregadas e os contadores recebidos da tela', async () => {
    servir([resumo(1, 'Regra · 17/09/2026'), resumo(2, 'Regra · 16/09/2026')])
    const conteiner = await montar({ quantidadeArquivadas: 1, quantidadeSalvas: 2 })

    expect(conteiner.text()).toContain('Synapse')
    expect(conteiner.text()).toContain('Nova Regra')
    expect(conteiner.text()).toContain('Regra · 17/09/2026')
    expect(conteiner.text()).toContain('Salvas2')
    expect(conteiner.text()).toContain('Arquivadas1')
    expect(conteiner.findAll('li')).toHaveLength(2)
    expect(conteiner.find('[role="status"]').exists()).toBe(false)
  })

  it('abre com as 12 regras mais recentes e indica que há mais para carregar', async () => {
    servir(criarJobs(30))
    const conteiner = await montar()

    expect(apiClient.listarJobs).toHaveBeenCalledExactlyOnceWith({ pagina: 0, tamanho: 12 })
    expect(linksDeRegras(conteiner)).toHaveLength(12)
    expect(conteiner.get('[role="status"]').text()).toBe('Carregando regras…')
  })

  it('carrega as regras antigas quando o fim da lista aparece na rolagem', async () => {
    servir(criarJobs(30))
    const conteiner = await montar()
    const observador = ObservadorControlavel.atual!

    expect(observador.opcoes.root).toBe(conteiner.get('ul').element)
    expect([...observador.alvos]).toEqual([conteiner.get('[role="status"]').element])

    observador.mostrarFimDaLista()
    await flushPromises()
    expect(linksDeRegras(conteiner)).toHaveLength(24)

    observador.mostrarFimDaLista()
    await flushPromises()
    expect(linksDeRegras(conteiner)).toHaveLength(30)
    expect(conteiner.get('ul a[href="/jobs/job-30"]').text()).toBe('Regra 30')
    expect(conteiner.find('[role="status"]').exists()).toBe(false)
    expect(observador.alvos.size).toBe(0)
    expect(apiClient.listarJobs).toHaveBeenCalledTimes(3)
  })

  it('continua carregando enquanto as regras não preenchem a altura da barra', async () => {
    ObservadorControlavel.fimVisivel = true
    servir(criarJobs(30))
    const conteiner = await montar()

    await vi.waitFor(() => expect(linksDeRegras(conteiner)).toHaveLength(30))
    expect(apiClient.listarJobs).toHaveBeenCalledTimes(3)
  })

  it('só diz que não há regras depois que a consulta confirma', async () => {
    let responder!: (pagina: PaginaJobs) => void
    vi.mocked(apiClient.listarJobs).mockReturnValue(
      new Promise((resolver) => {
        responder = resolver
      }),
    )
    const conteiner = await montar()

    expect(conteiner.text()).not.toContain('Nenhuma regra criada ainda.')
    expect(conteiner.get('[role="status"]').text()).toBe('Carregando regras…')

    responder({ itens: [], pagina: 0, tamanho: 12, total: 0 })
    await flushPromises()

    expect(conteiner.text()).toContain('Nenhuma regra criada ainda.')
    expect(conteiner.find('[role="status"]').exists()).toBe(false)
  })

  it('na falha, avisa sem expor o erro interno e permite tentar de novo', async () => {
    vi.mocked(apiClient.listarJobs).mockRejectedValueOnce(
      new HttpError(503, 'detalhe interno confidencial'),
    )
    const conteiner = await montar()

    expect(conteiner.get('[role="alert"]').text()).toContain('Não foi possível carregar as regras.')
    expect(conteiner.text()).not.toContain('confidencial')
    expect(conteiner.text()).not.toContain('Nenhuma regra criada ainda.')
    expect(conteiner.find('[role="status"]').exists()).toBe(false)

    servir(criarJobs(3))
    await conteiner.get('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(conteiner.find('[role="alert"]').exists()).toBe(false)
    expect(linksDeRegras(conteiner)).toHaveLength(3)
  })

  it('rola só a lista de regras e mantém Salvas e Arquivadas sempre à vista', async () => {
    servir(criarJobs(30))
    const conteiner = await montar()

    expect(conteiner.get('ul').classes()).toEqual(
      expect.arrayContaining(['min-h-0', 'flex-1', 'overflow-y-auto']),
    )
    expect(conteiner.get('ul').find('a[href="/salvas"]').exists()).toBe(false)
    expect(conteiner.get('nav').find('a[href="/salvas"]').exists()).toBe(true)
  })

  it('leva às listas do histórico', async () => {
    servir([])
    const conteiner = await montar({ secaoAtiva: 'arquivadas' })

    expect(conteiner.get('a[href="/salvas"]').text()).toContain('Salvas')
    expect(conteiner.get('a[href="/arquivadas"]').classes()).toContain('bg-[#4d3125]')
  })

  it('mantém o nome longo em uma linha, com reticências e o nome completo no title', async () => {
    const nomeLongo = `Comissão de novembro ${'x'.repeat(79)}`
    servir([resumo(1, nomeLongo)])
    const conteiner = await montar()

    const link = conteiner.get('li a')
    const texto = link.get('span')

    expect(nomeLongo).toHaveLength(100)
    expect(texto.text()).toBe(nomeLongo)
    expect(texto.classes()).toEqual(expect.arrayContaining(['truncate', 'min-w-0']))
    expect(link.attributes('title')).toBe(nomeLongo)
  })

  describe('edição inline', () => {
    async function montarComUmaRegra() {
      servir([resumo(1, 'Regra · 19/09/2026')])
      return montar()
    }

    async function abrirEdicao(conteiner: Awaited<ReturnType<typeof montar>>) {
      await conteiner.get('button[aria-label^="Renomear"]').trigger('click')
    }

    it('troca o rótulo por um campo com o nome atual ao clicar no lápis', async () => {
      const conteiner = await montarComUmaRegra()
      await abrirEdicao(conteiner)

      const campo = conteiner.get('input')
      expect((campo.element as HTMLInputElement).value).toBe('Regra · 19/09/2026')
      expect(conteiner.find('a[href="/jobs/job-1"]').exists()).toBe(false)
      conteiner.unmount()
    })

    it('não envia enquanto o nome não muda', async () => {
      const conteiner = await montarComUmaRegra()
      await abrirEdicao(conteiner)
      await conteiner.get('input').trigger('keydown.enter')

      expect(apiClient.renomearJob).not.toHaveBeenCalled()
      conteiner.unmount()
    })

    it('confirma com Enter e envia o nome digitado', async () => {
      vi.mocked(apiClient.renomearJob).mockResolvedValue({
        id: 'job-1',
        nome: 'Novo nome',
      } as never)
      const conteiner = await montarComUmaRegra()
      await abrirEdicao(conteiner)
      await conteiner.get('input').setValue('Novo nome')
      await conteiner.get('input').trigger('keydown.enter')
      await flushPromises()

      expect(apiClient.renomearJob).toHaveBeenCalledWith('job-1', { nome: 'Novo nome' })
      expect(usarStoreRenomearRegra().idEmEdicao).toBeNull()
      expect(conteiner.get('a[href="/jobs/job-1"]').text()).toBe('Novo nome')
      conteiner.unmount()
    })

    it('cancela com Esc sem chamar a API', async () => {
      const conteiner = await montarComUmaRegra()
      await abrirEdicao(conteiner)
      await conteiner.get('input').setValue('Outro')
      await conteiner.get('input').trigger('keydown.esc')

      expect(apiClient.renomearJob).not.toHaveBeenCalled()
      expect(conteiner.find('input').exists()).toBe(false)
      expect(conteiner.text()).toContain('Regra · 19/09/2026')
      conteiner.unmount()
    })

    it('mostra a mensagem da recusa e mantém o campo aberto', async () => {
      vi.mocked(apiClient.renomearJob).mockRejectedValue(
        new HttpError(403, 'Você não tem permissão para realizar esta ação.'),
      )
      const conteiner = await montarComUmaRegra()
      await abrirEdicao(conteiner)
      await conteiner.get('input').setValue('Novo')
      await conteiner.get('input').trigger('keydown.enter')
      await flushPromises()

      expect(conteiner.get('[role="alert"]').text()).toContain('Você não tem permissão')
      expect(conteiner.find('input').exists()).toBe(true)
      conteiner.unmount()
    })
  })
})
