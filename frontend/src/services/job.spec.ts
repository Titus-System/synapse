import { describe, expect, it } from 'vitest'
import { destinoDoJob } from './job'

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