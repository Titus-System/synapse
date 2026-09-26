import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CampoDeMultiSelecao from './CampoDeMultiSelecao.vue'

const opcoes = [
  { valor: '13', rotulo: 'LOJA-13' },
  { valor: '21', rotulo: 'LOJA-21' },
  { valor: '75', rotulo: 'LOJA-75' },
]

function montar(valores: string[] = []) {
  return mount(CampoDeMultiSelecao, {
    attachTo: document.body,
    props: {
      id: 'loja',
      rotulo: 'Loja',
      valores,
      opcoes,
      resumoPlural: 'lojas selecionadas',
      compacto: true,
    },
  })
}

function caixasDeSelecao(conteiner: ReturnType<typeof montar>) {
  return conteiner.get('#loja-painel').findAll('input[type="checkbox"]')
}

describe('CampoDeMultiSelecao', () => {
  it('resume o que está selecionado no gatilho do dropdown', () => {
    expect(montar().get('#loja').text()).toBe('Selecione uma opção')
    expect(montar(['21']).get('#loja').text()).toBe('LOJA-21')
    expect(montar(['13', '21']).get('#loja').text()).toBe('2 lojas selecionadas')
  })

  it('só mostra as opções depois de abrir o painel', async () => {
    const conteiner = montar()
    expect(conteiner.find('#loja-painel').exists()).toBe(false)

    await conteiner.get('#loja').trigger('click')

    expect(caixasDeSelecao(conteiner)).toHaveLength(3)
    expect(conteiner.get('#loja').attributes('aria-expanded')).toBe('true')
  })

  it('emite os códigos na ordem das opções, e não na ordem dos cliques', async () => {
    const conteiner = montar()
    await conteiner.get('#loja').trigger('click')

    await caixasDeSelecao(conteiner)[2]?.setValue(true)
    await conteiner.setProps({ valores: ['75'] })
    await caixasDeSelecao(conteiner)[0]?.setValue(true)

    expect(conteiner.emitted('update:valores')).toEqual([[['75']], [['13', '75']]])
  })

  it('desmarca um código já selecionado', async () => {
    const conteiner = montar(['13', '21'])
    await conteiner.get('#loja').trigger('click')

    await caixasDeSelecao(conteiner)[0]?.setValue(false)

    expect(conteiner.emitted('update:valores')).toEqual([[['21']]])
  })

  it('filtra as opções pelo rótulo e pelo código', async () => {
    const conteiner = montar()
    await conteiner.get('#loja').trigger('click')

    await conteiner.get('#loja-painel input[type="search"]').setValue('75')

    expect(conteiner.get('#loja-painel').findAll('label')).toHaveLength(1)
    expect(conteiner.get('#loja-painel').text()).toContain('LOJA-75')
  })

  // O campo vive dentro do formulário da regra: sem isso, o Enter no filtro
  // dispararia o envio.
  it('não deixa o Enter no filtro chegar ao formulário', async () => {
    const conteiner = montar()
    await conteiner.get('#loja').trigger('click')

    const teclaEnter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    conteiner.get('#loja-painel input[type="search"]').element.dispatchEvent(teclaEnter)

    expect(teclaEnter.defaultPrevented).toBe(true)
  })

  it('fecha o painel ao clicar fora do campo', async () => {
    const conteiner = montar()
    await conteiner.get('#loja').trigger('click')

    document.body.click()
    await conteiner.vm.$nextTick()

    expect(conteiner.find('#loja-painel').exists()).toBe(false)
    conteiner.unmount()
  })
})
