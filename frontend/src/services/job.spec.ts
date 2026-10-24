import { describe, expect, it } from 'vitest'
import { destinoDoJob, rotuloDaRegra } from './job'

const criadoEm = '2026-09-19T12:00:00Z'
const rotuloComData = `Regra · ${new Date(criadoEm).toLocaleDateString('pt-BR')}`

describe('destinoDoJob', () => {
  it('leva o job que aguarda correção ao chatbot', () => {
    expect(destinoDoJob({ id: 'job-1', status: 'aguardando_confirmacao_parametros' })).toBe(
      '/jobs/job-1/correcao',
    )
  })

  it.each(['gerando_regra', 'simulando', 'liberado', 'cancelado', 'arquivado', 'erro'] as const)(
    'mantém o destino padrão para %s',
    (status) => {
      expect(destinoDoJob({ id: 'job-1', status })).toBe('/jobs/job-1')
    },
  )

  it('escapa o identificador', () => {
    expect(destinoDoJob({ id: 'job 1', status: 'liberado' })).toBe('/jobs/job%201')
  })
})

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