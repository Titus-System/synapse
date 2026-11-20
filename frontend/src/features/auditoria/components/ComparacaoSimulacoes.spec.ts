import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComparacaoSimulacoes from './ComparacaoSimulacoes.vue'
import { ligarSimulacoes } from '../composables/simulacoesDossie'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { ComparacaoSimulacao, RegistroAuditoria } from '../types'

const comparacao: ComparacaoSimulacao = {
  resultado_id: 'res-2',
  resultado_anterior_id: 'res-1',
  baseline: { anterior: 540000, atual: 540000, variacao: 0 },
  simulado: { anterior: 598000, atual: 640000, variacao: 42000 },
  diferenca_abs: { anterior: 58000, atual: 100000, variacao: 42000 },
  diferenca_pct: { anterior: 0.1074, atual: 0.1852, variacao: 0.0778 },
}
function registro(): RegistroAuditoria {
  const r = structuredClone(registroExemplo)
  r.resultados = [1, 2].map((i) => ({
    id: `res-${i}`,
    codigo_gerado_id: r.codigos[0]!.id,
    status: 'sucesso' as const,
    proposito: 'simulacao' as const,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  r.simulacoes = [1, 2].map((i) => ({
    id: `sim-${i}`,
    regra_id: r.versoes[1]!.id,
    codigo_gerado_id: r.codigos[0]!.id,
    resultado_id: `res-${i}`,
    flag_baixa_rastreabilidade: false,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  return r
}
const lista = (c?: ComparacaoSimulacao) => ligarSimulacoes(registro(), c ? [c] : [])

describe('ComparacaoSimulacoes', () => {
  it('mostra anterior, atual e a variação que veio do resumo', () => {
    const [a, b] = lista(comparacao)
    const w = mount(ComparacaoSimulacoes, { props: { item: b!, anterior: a } })
    const simulado = w.get('[data-indicador="simulado"]').text()
    expect(simulado).toContain('R$ 598.000,00')
    expect(simulado).toContain('R$ 640.000,00')
    expect(simulado).toContain('+R$ 42.000,00')
    expect(w.get('[data-indicador="diferenca_pct"]').text()).toContain('7,78%')
    expect(w.text()).toContain('SIMULAÇÃO 1 → SIMULAÇÃO 2')
  })

  it('não põe sinal na variação zero', () => {
    const [a, b] = lista(comparacao)
    const w = mount(ComparacaoSimulacoes, { props: { item: b!, anterior: a } })
    expect(w.get('[data-indicador="baseline"]').text()).not.toContain('+')
  })

  it('omite orçamento e meta quando o resumo não os traz', () => {
    const [, b] = lista(comparacao)
    const w = mount(ComparacaoSimulacoes, { props: { item: b! } })
    expect(w.find('[data-indicador="orcamento"]').exists()).toBe(false)
    expect(w.find('[data-indicador="meta_venda"]').exists()).toBe(false)
  })

  it('mostra orçamento e meta quando existem', () => {
    const completa = {
      ...comparacao,
      orcamento: { anterior: 600000, atual: 650000, variacao: 50000 },
      meta_venda: { anterior: 1, atual: 1, variacao: 0 },
    }
    const [, b] = lista(completa)
    const w = mount(ComparacaoSimulacoes, { props: { item: b! } })
    expect(w.get('[data-indicador="orcamento"]').text()).toContain('+R$ 50.000,00')
    expect(w.find('[data-indicador="meta_venda"]').exists()).toBe(true)
  })

  it('identifica as simulações comparadas, com o horário, no cabeçalho', () => {
    const [a, b] = lista(comparacao)
    const w = mount(ComparacaoSimulacoes, { props: { item: b!, anterior: a } })
    expect(w.get('[data-coluna="anterior"]').text()).toContain('Simulação 1')
    expect(w.get('[data-coluna="anterior"]').text()).toContain('28/11/2025')
    expect(w.get('[data-coluna="atual"]').text()).toContain('Simulação 2')
  })

  it('sem a simulação anterior na lista, chama a coluna de anterior', () => {
    const [, b] = lista(comparacao)
    const w = mount(ComparacaoSimulacoes, { props: { item: b! } })
    expect(w.get('[data-coluna="anterior"]').text()).toBe('Anterior')
  })

  it('não mostra o bloco sem comparação', () => {
    const [a] = lista()
    const w = mount(ComparacaoSimulacoes, { props: { item: a! } })
    expect(w.find('section').exists()).toBe(false)
  })
})