import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SimulacoesFinalizacao from './SimulacoesFinalizacao.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { RegistroAuditoria, ResumoDossie } from '../types'

const totais = { baseline: 1000, simulado: 1500, diferenca_abs: 500, diferenca_pct: 0.5 }
const ind = { anterior: 1, atual: 2, variacao: 1 }
function tres(): RegistroAuditoria {
  const r = structuredClone(registroExemplo)
  const status = ['erro_codigo', 'sucesso', 'sucesso'] as const
  r.resultados = status.map((s, i) => ({
    id: `res-${i + 1}`,
    codigo_gerado_id: r.codigos[0]!.id,
    status: s,
    proposito: 'simulacao' as const,
    totais: s === 'sucesso' ? totais : null,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  r.simulacoes = status.map((_, i) => ({
    id: `sim-${i + 1}`,
    regra_id: r.versoes[1]!.id,
    codigo_gerado_id: r.codigos[0]!.id,
    resultado_id: `res-${i + 1}`,
    flag_baixa_rastreabilidade: false,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  return r
}
const resumo: ResumoDossie = {
  simulacoes: { registradas: 3, sucesso: 2, falha: 1 },
  versao_vigente: 2,
  versoes: [],
  comparacoes: [
    {
      resultado_id: 'res-3',
      resultado_anterior_id: 'res-2',
      baseline: ind,
      simulado: ind,
      diferenca_abs: ind,
      diferenca_pct: ind,
    },
  ],
}

describe('SimulacoesFinalizacao', () => {
  it('mostra os contadores 3, 2 e 1 e a versão vigente', () => {
    const w = mount(SimulacoesFinalizacao, { props: { registro: tres(), resumo } })
    expect(w.get('[data-contador="registradas"]').text()).toContain('3')
    expect(w.get('[data-contador="sucesso"]').text()).toContain('2')
    expect(w.get('[data-contador="falha"]').text()).toContain('1')
    expect(w.get('[data-contador="vigente"]').text()).toContain('v2')
  })

  it('seleciona a última simulação e mostra a comparação com a anterior', () => {
    const w = mount(SimulacoesFinalizacao, { props: { registro: tres(), resumo } })
    expect(w.get('[aria-label="Simulação selecionada"]').text()).toContain('Simulação selecionada · 3')
    expect(w.text()).toContain('SIMULAÇÃO 2 → SIMULAÇÃO 3')
  })

  it('a simulação 1 não tem totais nem comparação', async () => {
    const w = mount(SimulacoesFinalizacao, { props: { registro: tres(), resumo } })
    const botao = w.get('[data-simulacao="1"]').findAll('button').find((b) => b.text() === 'Consultar registro →')!
    await botao.trigger('click')
    expect(w.get('[aria-label="Simulação selecionada"]').text()).toContain('não tem totais')
    expect(w.find('[aria-label="Comparação com a simulação anterior"]').exists()).toBe(false)
  })

  it('sem resumo mostra o erro e mantém a lista', () => {
    const w = mount(SimulacoesFinalizacao, {
      props: { registro: tres(), erroResumo: 'Falha ao carregar.' },
    })
    expect(w.get('[role="alert"]').text()).toContain('Falha ao carregar.')
    expect(w.find('[data-simulacao="1"]').exists()).toBe(true)
  })
})