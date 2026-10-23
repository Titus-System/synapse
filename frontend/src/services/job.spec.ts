import { describe, expect, it } from 'vitest'
import { rotuloDaRegra } from './job'

const criadoEm = '2026-09-19T12:00:00Z'
const rotuloComData = `Regra · ${new Date(criadoEm).toLocaleDateString('pt-BR')}`

describe('rotuloDaRegra', () => {
  it('devolve o nome quando o job tem nome', () => {
    expect(rotuloDaRegra({ nome: 'Comissão de novembro', criado_em: criadoEm })).toBe(
      'Comissão de novembro',
    )
  })

  it.each([
    ['ausente', undefined],
    ['nulo', null],
    ['vazio', ''],
    ['só com espaços', '   '],
  ])('devolve o rótulo com a data quando o nome é %s', (_caso, nome) => {
    expect(rotuloDaRegra({ nome, criado_em: criadoEm })).toBe(rotuloComData)
  })

  it('usa o formato DD/MM/AAAA no rótulo com a data', () => {
    expect(rotuloDaRegra({ criado_em: criadoEm })).toMatch(/^Regra · \d{2}\/\d{2}\/\d{4}$/)
  })
})