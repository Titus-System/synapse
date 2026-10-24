import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { usarStoreRenomearRegra } from '@/stores/renomearRegra'
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

beforeEach(() => {
  vi.resetAllMocks()
})

describe('TheSidebar', () => {
  it('apresenta as regras recentes recebidas da tela', () => {
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem(),
      props: {
        quantidadeArquivadas: 1,
        quantidadeSalvas: 2,
        regrasRecentes: [
          { identificador: 'job-1', rotulo: 'Regra · 17/09/2026' },
          { identificador: 'job-2', rotulo: 'Regra · 16/09/2026' },
        ],
      },
    })

    expect(conteiner.text()).toContain('Synapse')
    expect(conteiner.text()).toContain('Nova Regra')
    expect(conteiner.text()).toContain('Regra · 17/09/2026')
    expect(conteiner.text()).toContain('Salvas2')
    expect(conteiner.text()).toContain('Arquivadas1')
    expect(conteiner.findAll('li')).toHaveLength(2)
  })

  it('informa quando não há regras recentes', () => {
    const conteiner = mount(TheSidebar, { ...opcoesDeMontagem(), props: { regrasRecentes: [] } })

    expect(conteiner.text()).toContain('Nenhuma regra criada ainda.')
  })

  it('leva o atalho ao destino informado', () => {
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem(),
      props: {
        regrasRecentes: [
          { identificador: 'job-1', rotulo: 'Pendente', destino: '/jobs/job-1/correcao' },
        ],
      },
    })

    expect(conteiner.get('li a').attributes('href')).toBe('/jobs/job-1/correcao')
  })

  it('mantém o destino padrão quando o atalho não informa um', () => {
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem(),
      props: { regrasRecentes: [{ identificador: 'job-1', rotulo: 'Regra' }] },
    })

    expect(conteiner.get('li a').attributes('href')).toBe('/jobs/job-1')
  })

  it('leva às listas do histórico', () => {
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem(),
      props: { secaoAtiva: 'arquivadas' },
    })

    expect(conteiner.get('a[href="/salvas"]').text()).toContain('Salvas')
    expect(conteiner.get('a[href="/arquivadas"]').classes()).toContain('bg-[#4d3125]')
  })

  it('mantém o nome longo em uma linha, com reticências e o nome completo no title', () => {
    const nomeLongo = `Comissão de novembro ${'x'.repeat(79)}`
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem(),
      props: { regrasRecentes: [{ identificador: 'job-1', rotulo: nomeLongo }] },
    })

    const link = conteiner.get('li a')
    const texto = link.get('span')

    expect(nomeLongo).toHaveLength(100)
    expect(texto.text()).toBe(nomeLongo)
    expect(texto.classes()).toEqual(expect.arrayContaining(['truncate', 'min-w-0']))
    expect(link.attributes('title')).toBe(nomeLongo)
  })

  describe('edição inline', () => {
    const regras = [{ identificador: 'job-1', rotulo: 'Regra · 19/09/2026' }]

    function montar() {
      return mount(TheSidebar, {
        ...opcoesDeMontagem(),
        props: { regrasRecentes: regras },
        attachTo: document.body,
      })
    }

    async function abrirEdicao(conteiner: ReturnType<typeof montar>) {
      await conteiner.get('button[aria-label^="Renomear"]').trigger('click')
    }

    it('troca o rótulo por um campo com o nome atual ao clicar no lápis', async () => {
      const conteiner = montar()
      await abrirEdicao(conteiner)

      const campo = conteiner.get('input')
      expect((campo.element as HTMLInputElement).value).toBe('Regra · 19/09/2026')
      expect(conteiner.find('a[href="/jobs/job-1"]').exists()).toBe(false)
      conteiner.unmount()
    })

    it('não envia enquanto o nome não muda', async () => {
      const conteiner = montar()
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
      const conteiner = montar()
      await abrirEdicao(conteiner)
      await conteiner.get('input').setValue('Novo nome')
      await conteiner.get('input').trigger('keydown.enter')
      await flushPromises()

      expect(apiClient.renomearJob).toHaveBeenCalledWith('job-1', { nome: 'Novo nome' })
      expect(usarStoreRenomearRegra().idEmEdicao).toBeNull()
      conteiner.unmount()
    })

    it('cancela com Esc sem chamar a API', async () => {
      const conteiner = montar()
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
      const conteiner = montar()
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
