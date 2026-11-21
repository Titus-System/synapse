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
const montarRegistro = (r: RegistroAuditoria) =>
  mount(DetalheSimulacao, { props: { item: ligarSimulacoes(r)[0]!, responsavel: 'rh.exemplo' } })
const montar = (status: 'sucesso' | 'erro_codigo') => montarRegistro(registro(status))

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
  it('não mostra o id do código, só o botão de copiar com o id no title', () => {
    const w = montar('sucesso')
    const id = registroExemplo.codigos[0]!.id
    expect(w.text()).not.toContain(id.slice(0, 8))
    expect(w.find(`button[title="${id}"]`).exists()).toBe(true)
  })

  it('alinha as seções de quebra ao topo, sem esticá-las', () => {
    const w = montar('sucesso')
    expect(w.get('[data-quebras] .grid').classes()).toContain('items-start')
  })

  it('mostra as fontes do resultado, inclusive o de falha', () => {
    const r = registro('erro_codigo')
    r.resultados[0]!.fontes = {
      manifesto: { versao: 2, congelamento: '2026-10-15' },
      competencias: ['2025-11'],
      arquivos: [{ nome: 'vendas.csv', sha256: 'e'.repeat(64) }],
      baselines: [{ competencia: '2025-11', arquivo: 'baselines/2025-11.json', sha256: 'f'.repeat(64) }],
    }
    const w = montarRegistro(r)
    expect(w.get('[data-versao-bases]').text()).toBe('v2')
    expect(w.get('[data-arquivos]').text()).toContain('e'.repeat(64))
    expect(w.get('[data-baseline="2025-11"]').text()).toContain('f'.repeat(64))
  })

  it('mostra o estado sem fontes no resultado gravado sem elas', () => {
    expect(montar('sucesso').get('[data-sem-fontes]').text()).toContain('Sem fontes registradas')
  })

  it('não mostra fontes na simulação sem resultado', () => {
    const r = registro('sucesso')
    delete r.simulacoes[0]!.resultado_id
    const w = montarRegistro(r)
    expect(w.find('[data-fontes]').exists()).toBe(false)
  })

  it('mostra a versão e o código usados juntos e o responsável', () => {
    const w = montar('sucesso')
    const versao = w.get('[data-versao-utilizada]')
    expect(versao.text().replace(/\s+/g, ' ')).toContain('v2 · código Copiar id')
    expect(versao.find(`button[title="${registroExemplo.codigos[0]!.id}"]`).exists()).toBe(true)
    expect(w.get('[data-responsavel]').text()).toBe('rh.exemplo')
  })

  it('destaca simulado e diferença como vieram, com o sinal e o veredito', () => {
    const w = montar('sucesso')
    const simulado = w.get('[data-destaque="simulado"]')
    expect(simulado.text()).toContain('R$ 1.500,00')
    expect(simulado.text()).toContain('Baseline: R$ 1.000,00')
    const diferenca = w.get('[data-destaque="diferenca"]')
    expect(diferenca.text()).toContain('+R$ 500,00')
    expect(diferenca.text()).toContain('+50,00%')
    expect(diferenca.text()).toContain('Viável')
    expect(diferenca.classes()).toContain('bg-[#e4f2e7]')
  })

  it('pinta os destaques pelo veredito que a API devolveu', () => {
    const r = registro('sucesso')
    r.resultados[0]!.veredito = 'inviavel'
    expect(montarRegistro(r).get('[data-destaque="simulado"]').classes()).toContain('bg-[#fde4e0]')
  })

  it('mostra a explicação do resultado', () => {
    const r = registro('sucesso')
    r.explicacoes = [
      {
        id: 'exp-1',
        resultado_id: 'res-1',
        texto: 'A comissão simulada está dentro do orçamento.',
        aderencia_conferida: true,
        criado_em: '2025-11-28T14:12:00Z',
      },
    ]
    const w = montarRegistro(r)
    expect(w.get('[data-explicacao]').text()).toContain('A comissão simulada está dentro do orçamento.')
    expect(w.find('[data-sem-aderencia]').exists()).toBe(false)
  })

  it('avisa quando a explicação cita número que não corresponde ao apurado', () => {
    const r = registro('sucesso')
    r.explicacoes = [
      {
        id: 'exp-1',
        resultado_id: 'res-1',
        texto: 'A comissão simulada é de R$ 9,00.',
        aderencia_conferida: false,
        criado_em: '2025-11-28T14:12:00Z',
      },
    ]
    expect(montarRegistro(r).get('[data-sem-aderencia]').text()).toContain(
      'não corresponde ao apurado',
    )
  })

  it('sem explicação não mostra o bloco', () => {
    expect(montar('sucesso').find('[data-explicacao]').exists()).toBe(false)
  })

  it('marca o resultado como registrado, sem execução pelo auditor', () => {
    expect(montar('erro_codigo').get('[data-selo-registro]').text()).toBe(
      'Resultado registrado · sem execução pelo auditor',
    )
    const r = registro('sucesso')
    delete r.simulacoes[0]!.resultado_id
    expect(montarRegistro(r).find('[data-selo-registro]').exists()).toBe(false)
  })
})