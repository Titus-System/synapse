import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DetalheSimulacao from './DetalheSimulacao.vue'
import { ligarSimulacoes } from '../composables/simulacoesDossie'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { RegistroAuditoria } from '../types'

function registro(status: 'sucesso' | 'erro_codigo'): RegistroAuditoria {
  const r = structuredClone(registroExemplo)
  const ok = status === 'sucesso'
  r.resultados = [
    {
      id: 'res-1',
      codigo_gerado_id: r.codigos[0]!.id,
      status,
      proposito: 'simulacao',
      veredito: ok ? 'viavel' : undefined,
      meta_venda: 28000000,
      totais: ok
        ? { baseline: 1000, simulado: 1500, diferenca_abs: 500, diferenca_pct: 0.5, orcamento: 2000 }
        : null,
      decomposicao: ok
        ? {
            elemento: { 'nucleo.percentual': 500 },
            loja: { '13': 500 },
            marca: { '10': 300, '20': 200 },
            cargo: { '100': 500 },
            competencia: { '2025-11': 500 },
            // @ts-expect-error a quebra por matrícula existe na API e não pode aparecer
            matricula: { 'MATRIC-422': 141300 },
          }
        : null,
      criado_em: '2025-11-28T14:11:00Z',
    },
  ]
  r.simulacoes = [
    {
      id: 'sim-1',
      regra_id: r.versoes[1]!.id,
      codigo_gerado_id: r.codigos[0]!.id,
      resultado_id: 'res-1',
      flag_baixa_rastreabilidade: false,
      criado_em: '2025-11-28T14:09:00Z',
    },
  ]
  return r
}
const montar = (status: 'sucesso' | 'erro_codigo') =>
  mount(DetalheSimulacao, { props: { item: ligarSimulacoes(registro(status))[0]! } })

describe('DetalheSimulacao', () => {
  it('mostra versão, códigos de loja, marca e cargo, parâmetros e totais', () => {
    const w = montar('sucesso')
    const texto = w.text()
    expect(texto).toContain('v2')
    expect(w.get('[data-escopo]').text()).toContain('13 / 10, 20 / 100, 300')
    expect(texto).toContain('2025-11')
    expect(texto).toContain('R$ 2.000,00')
    expect(texto).toContain('R$ 28.000.000,00')
    expect(w.get('[data-totais]').text()).toContain('R$ 1.500,00')
    expect(w.get('[data-totais]').text()).toContain('Viável')
  })

  it('mostra a quebra da diferença por código, sem matrícula', () => {
    const w = montar('sucesso')
    expect(w.findAll('[data-quebra]').map((d) => d.attributes('data-quebra'))).toEqual([
      'loja',
      'marca',
      'cargo',
      'competencia',
    ])
    expect(w.get('[data-quebra="marca"]').text()).toContain('Código 10')
    expect(w.text()).not.toContain('MATRIC-422')
    expect(w.text().toLowerCase()).not.toContain('matrícula')
  })

  it('sem sucesso mostra a situação sem totais nem quebras', () => {
    const w = montar('erro_codigo')
    expect(w.text()).toContain('Erro no código')
    expect(w.find('[data-quebras]').exists()).toBe(false)
    expect(w.get('[data-totais]').text()).toContain('não tem totais')
    expect(w.text()).not.toContain('R$ 1.500,00')
  })
})