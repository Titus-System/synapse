import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ConversaAuditoria from './ConversaAuditoria.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'

describe('ConversaAuditoria', () => {
  it('mostra os itens na ordem em que foram registrados', () => {
    const wrapper = mount(ConversaAuditoria, { props: { registro: registroExemplo } })
    expect(wrapper.findAll('[data-item]').map((i) => i.attributes('data-item'))).toEqual([
      'entrada', 'chamada', 'versao', 'conflitos', 'entrada', 'chamada', 'versao', 'chamada', 'codigo',
    ])
  })

  it('identifica autor, tipo e rodada de cada entrada', () => {
    const entradas = mount(ConversaAuditoria, { props: { registro: registroExemplo } }).findAll(
      '[data-item="entrada"]',
    )
    expect(entradas[0]!.text()).toContain('rh.exemplo')
    expect(entradas[0]!.text()).toContain('voz')
    expect(entradas[1]!.text()).toContain('Correção')
    expect(entradas[1]!.text()).toContain('rodada 1')
  })

  it('mostra o motivo dos conflitos e não as referências internas', () => {
    const texto = mount(ConversaAuditoria, { props: { registro: registroExemplo } })
      .get('[data-item="conflitos"]')
      .text()
    expect(texto).toContain('percentual ausente')
    expect(texto).not.toContain('nucleo.percentual')
  })

  it('exibe marcação HTML da entrada como texto', () => {
    const registro = structuredClone(registroExemplo)
    registro.entradas[0]!.texto = '<img src=x onerror=alert(1)><b>x</b>'
    const wrapper = mount(ConversaAuditoria, { props: { registro } })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)><b>x</b>')
  })

  it('tem rolagem própria e informa conversa vazia', () => {
    const wrapper = mount(ConversaAuditoria, { props: { registro: registroExemplo } })
    expect(wrapper.get('ol').classes()).toContain('overflow-y-auto')
    const vazio = structuredClone(registroExemplo)
    Object.assign(vazio, { entradas: [], rodadas: [], versoes: [], codigos: [], chamadas_modelo: [] })
    expect(mount(ConversaAuditoria, { props: { registro: vazio } }).text()).toContain(
      'Nenhum registro na conversa',
    )
  })
  it('mostra a situação da rodada junto dos conflitos', () => {
    const texto = mount(ConversaAuditoria, { props: { registro: registroExemplo } })
      .get('[data-item="conflitos"]')
      .text()
    expect(texto).toContain('Situação: Corrigida')
  })

  it('mostra a correção registrada só na rodada como mensagem do usuário', () => {
    const registro = structuredClone(registroExemplo)
    registro.entradas = registro.entradas.filter((e) => e.finalidade !== 'correcao')
    const wrapper = mount(ConversaAuditoria, { props: { registro } })
    const msg = wrapper.get('[data-item="correcao_rodada"]').text()
    expect(msg).toContain('rh.exemplo')
    expect(msg).toContain('O percentual de comissão é 2,5%.')
  })

  it('mostra o id curto dos marcos de versão e código e guarda o completo no title', () => {
    const wrapper = mount(ConversaAuditoria, { props: { registro: registroExemplo } })
    const codigo = registroExemplo.codigos[0]!.id
    const versao = registroExemplo.versoes[0]!.id
    expect(wrapper.get('[data-item="codigo"]').text()).toContain(codigo.slice(0, 8))
    expect(wrapper.get('[data-item="codigo"]').text()).not.toContain(codigo)
    expect(wrapper.find(`[data-item="codigo"] [title="${codigo}"]`).exists()).toBe(true)
    expect(wrapper.find(`[data-item="versao"] [title="${versao}"]`).exists()).toBe(true)
  })
})