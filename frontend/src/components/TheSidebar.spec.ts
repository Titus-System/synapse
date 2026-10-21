import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TheSidebar from './TheSidebar.vue'

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

describe('TheSidebar', () => {
  it('apresenta as regras recentes recebidas da tela', () => {
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem,
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
    const conteiner = mount(TheSidebar, { ...opcoesDeMontagem, props: { regrasRecentes: [] } })

    expect(conteiner.text()).toContain('Nenhuma regra criada ainda.')
  })

  it('leva às listas do histórico', () => {
    const conteiner = mount(TheSidebar, { ...opcoesDeMontagem, props: { secaoAtiva: 'arquivadas' } })

    expect(conteiner.get('a[href="/salvas"]').text()).toContain('Salvas')
    expect(conteiner.get('a[href="/arquivadas"]').classes()).toContain('bg-[#4d3125]')
  })

  it('mantém o nome longo em uma linha, com reticências e o nome completo no title', () => {
    const nomeLongo = `Comissão de novembro ${'x'.repeat(79)}`
    const conteiner = mount(TheSidebar, {
      ...opcoesDeMontagem,
      props: { regrasRecentes: [{ identificador: 'job-1', rotulo: nomeLongo }] },
    })

    const link = conteiner.get('li a')
    const texto = link.get('span')

    expect(nomeLongo).toHaveLength(100)
    expect(texto.text()).toBe(nomeLongo)
    expect(texto.classes()).toEqual(expect.arrayContaining(['truncate', 'min-w-0']))
    expect(link.attributes('title')).toBe(nomeLongo)
  })
})
