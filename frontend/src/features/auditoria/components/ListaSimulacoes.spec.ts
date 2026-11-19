import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ListaSimulacoes from './ListaSimulacoes.vue'
import { ligarSimulacoes } from '../composables/simulacoesDossie'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { RegistroAuditoria } from '../types'

const totais = {
  baseline: 1000,
  simulado: 1500,
  diferenca_abs: 500,
  diferenca_pct: 0.5,
  orcamento: 2000,
}
function tres(): RegistroAuditoria {
  const r = structuredClone(registroExemplo)
  const regra = r.versoes[1]!.id
  const codigo = r.codigos[0]!.id
  const status = ['erro_codigo', 'sucesso', 'sucesso'] as const
  r.resultados = status.map((s, i) => ({
    id: `res-${i + 1}`,
    codigo_gerado_id: codigo,
    status: s,
    proposito: 'simulacao' as const,
    totais: s === 'sucesso' ? totais : null,
    meta_venda: 28000000,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  r.simulacoes = status.map((_, i) => ({
    id: `sim-${i + 1}`,
    regra_id: regra,
    codigo_gerado_id: codigo,
    resultado_id: `res-${i + 1}`,
    flag_baixa_rastreabilidade: false,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  return r
}
function montar(selecionada?: string) {
  return mount(ListaSimulacoes, {
    props: { simulacoes: ligarSimulacoes(tres()), selecionada },
  })
}

describe('ListaSimulacoes', () => {
  it('lista as três simulações, a primeira em erro e sem totais', () => {
    const wrapper = montar()
    expect(wrapper.findAll('[data-simulacao]').map((l) => l.attributes('data-simulacao'))).toEqual([
      '1',
      '2',
      '3',
    ])
    const primeira = wrapper.get('[data-simulacao="1"]').text()
    expect(primeira).toContain('Erro no código')
    expect(primeira).toContain('Sem totais')
    expect(primeira).not.toContain('R$ 1.000,00')
  })

  it('mostra totais e parâmetros das simulações com sucesso', () => {
    const segunda = montar().get('[data-simulacao="2"]').text()
    expect(segunda).toContain('Concluída')
    expect(segunda).toContain('R$ 1.000,00')
    expect(segunda).toContain('R$ 1.500,00')
    expect(segunda).toContain('R$ 2.000,00')
    expect(segunda).toContain('R$ 28.000.000,00')
    expect(segunda).toContain('2025-11')
    expect(segunda).toContain('Versão 2')
  })

  it('emite a seleção e destaca a escolhida', async () => {
    const wrapper = montar('sim-3')
    expect(wrapper.get('[data-simulacao="3"]').text()).toContain('Selecionada')
    const botao = wrapper.get('[data-simulacao="2"]').findAll('button').find((b) => b.text() === 'Consultar registro →')!
    await botao.trigger('click')
    expect(wrapper.emitted('selecionar')![0]).toEqual(['sim-2'])
  })

  it('informa quando não há simulações', () => {
    const wrapper = mount(ListaSimulacoes, { props: { simulacoes: [] } })
    expect(wrapper.text()).toContain('Nenhuma simulação registrada')
  })
})