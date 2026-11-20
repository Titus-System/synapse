import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FinalizacaoDossie from './FinalizacaoDossie.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { EvidenciasVersao } from '../composables/simulacoesDossie'

const acao = { id: 'a1', acao: 'salvar' as const, executado_em: '2025-11-28T14:18:00Z' }
const evidencias: EvidenciasVersao = {
  versao: registroExemplo.versoes[1]!,
  codigos: [registroExemplo.codigos[0]!],
  simulacoes: [2, 3],
}
const base = { regra: 'Comissão de novembro', responsavel: 'rh.exemplo' }

describe('FinalizacaoDossie', () => {
  it('mostra a ação, o horário e a versão vigente', () => {
    const w = mount(FinalizacaoDossie, {
      props: { ...base, finalizacao: { acao }, versaoVigente: 2, evidencias },
    })
    expect(w.get('[data-acao]').text()).toBe('Salvar')
    expect(w.get('[data-acao]').attributes('title')).toBe('salvar')
    expect(w.get('[data-registrada]').text()).toContain('28/11/2025')
    expect(w.get('[data-versao]').text()).toBe('v2')
    expect(w.get('[data-aceite]').text()).toBe('Sem aceite registrado')
  })

  it('mostra quem finalizou, o nome, o escopo e a vigência da versão vigente', () => {
    const w = mount(FinalizacaoDossie, {
      props: { ...base, finalizacao: { acao }, versaoVigente: 2, evidencias },
    })
    expect(w.get('[data-finalizada-por]').text()).toBe('Finalizada por rh.exemplo')
    expect(w.get('[data-nome-regra]').text()).toBe('Comissão de novembro')
    expect(w.get('[data-escopo]').text()).toBe('13 / 10, 20')
    expect(w.get('[data-vigencia]').text()).toBe('11/2025')
    expect(w.get('[data-registrada]').text()).toContain('· rh.exemplo')
  })

  it('liga a versão vigente ao código e às simulações dela', () => {
    const w = mount(FinalizacaoDossie, {
      props: { ...base, finalizacao: { acao }, versaoVigente: 2, evidencias },
    })
    const texto = w.get('[data-evidencias]').text().replace(/\s+/g, ' ')
    expect(texto).toBe('v2 · código Copiar id · simulações 2 e 3')
    expect(
      w.find(`[data-evidencias] button[title="${registroExemplo.codigos[0]!.id}"]`).exists(),
    ).toBe(true)
  })

  it('diz quando a versão vigente não tem simulação', () => {
    const w = mount(FinalizacaoDossie, {
      props: {
        ...base,
        finalizacao: { acao },
        versaoVigente: 2,
        evidencias: { ...evidencias, codigos: [], simulacoes: [] },
      },
    })
    expect(w.get('[data-evidencias]').text().replace(/\s+/g, ' ')).toBe('v2 · nenhuma simulação')
  })

  it('mostra o aceite da meta sugerida quando houver', () => {
    const aceite = { regra_id: 'x', criada_em: '2025-11-28T14:16:00Z', aceita_em: '2025-11-28T14:17:00Z' }
    const w = mount(FinalizacaoDossie, {
      props: { ...base, finalizacao: { acao, aceite }, versaoVigente: 2, evidencias },
    })
    expect(w.get('[data-aceite]').text()).toContain('Aceita em')
  })

  it('tolera versão vigente ausente', () => {
    const w = mount(FinalizacaoDossie, { props: { ...base, finalizacao: { acao } } })
    expect(w.find('[data-versao]').exists()).toBe(false)
    expect(w.get('[data-evidencias]').text()).toBe('Não informadas')
    expect(w.get('[data-vigencia]').text()).toBe('Não informada')
  })

  it('informa quando não há ação de fechamento', () => {
    const w = mount(FinalizacaoDossie, { props: base })
    expect(w.text()).toContain('Nenhuma ação de fechamento registrada')
    expect(w.find('[data-finalizada-por]').exists()).toBe(false)
  })
})
