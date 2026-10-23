import { expect, it } from 'vitest'
import { formatarReais, organizarLinhas, rotulosContribuicoes } from './apresentacaoDetalhamento'

it('apresenta cada competência e matrícula preservando todos os valores do servidor', () => {
  const linha = {
    cod_loja: '001',
    cod_marca: '010',
    cod_cargo: '100',
    comissao_baseline: 100,
    comissao_simulada: 150,
    diferenca: 49.99,
    contribuicoes: { 'elem.1': 49.99 },
  }
  expect(organizarLinhas({ '2025-08': { '0001': linha }, '2025-09': { '0001': linha } })).toEqual([
    { competencia: '2025-08', matricula: '0001', ...linha },
    { competencia: '2025-09', matricula: '0001', ...linha },
  ])
  expect(formatarReais(linha.diferenca)).toBe('R$ 49,99')
})

it('nomeia as contribuições pela regra sem apresentar referências nem construtos internos', () => {
  const rotulos = rotulosContribuicoes({
    nucleo: { percentual: 0.025 },
    especificacoes: [
      { ref: 'elem.7', construto: 'bonus_fixo', valor: 10 },
      { ref: 'elem.2', construto: 'futuro' },
    ],
  })
  expect(rotulos['nucleo.percentual']).toEqual({ rotulo: 'Comissão de 2,5%' })
  expect(rotulos['elem.7']).toEqual({
    rotulo: 'Bônus fixo de R$ 10,00 · condição 1',
    descricao: undefined,
  })
  expect(rotulos['elem.2']).toEqual({
    rotulo: 'Condição adicional · condição 2',
    descricao: undefined,
  })
  expect(Object.values(rotulos).map((r) => r.rotulo).join(' ')).not.toMatch(
    /nucleo\.|elem\.|bonus_fixo|futuro/,
  )
})

it('separa do rótulo curto o texto da condição adicional', () => {
  const descricao = 'Para cada vendedor do cargo 100, bônus de R$ 350,00 acima de R$ 40.000,00.'
  const rotulos = rotulosContribuicoes({
    nucleo: {},
    especificacoes: [{ ref: 'elem.1', construto: 'generico', descricao }],
  })

  expect(rotulos['elem.1']).toEqual({ rotulo: 'Condição adicional · condição 1', descricao })
})
