import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FinalizacaoDossie from './FinalizacaoDossie.vue'

const acao = { id: 'a1', acao: 'salvar' as const, executado_em: '2025-11-28T14:18:00Z' }

describe('FinalizacaoDossie', () => {
  it('mostra a ação, o horário e a versão vigente', () => {
    const w = mount(FinalizacaoDossie, { props: { finalizacao: { acao }, versaoVigente: 2 } })
    expect(w.get('[data-acao]').text()).toBe('Salvar')
    expect(w.get('[data-acao]').attributes('title')).toBe('salvar')
    expect(w.text()).toContain('28/11/2025')
    expect(w.get('[data-versao]').text()).toBe('v2')
    expect(w.get('[data-aceite]').text()).toBe('Sem aceite registrado')
  })

  it('mostra o aceite da meta sugerida quando houver', () => {
    const aceite = { regra_id: 'x', criada_em: '2025-11-28T14:16:00Z', aceita_em: '2025-11-28T14:17:00Z' }
    const w = mount(FinalizacaoDossie, { props: { finalizacao: { acao, aceite }, versaoVigente: 2 } })
    expect(w.get('[data-aceite]').text()).toContain('Aceita em')
  })

  it('tolera versão vigente ausente', () => {
    const w = mount(FinalizacaoDossie, { props: { finalizacao: { acao } } })
    expect(w.get('[data-versao]').text()).toBe('Não informada')
  })

  it('informa quando não há ação de fechamento', () => {
    const w = mount(FinalizacaoDossie, { props: {} })
    expect(w.text()).toContain('Nenhuma ação de fechamento registrada')
  })
})