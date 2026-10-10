import { describe, expect, it } from 'vitest'
import { calcularProgresso, MENSAGEM_DE_ESPERA_DO_PROVEDOR } from './progressoSimulacao'
import type { EventoEtapa } from '@/types/api'

const etapa = (etapaNome: string, status: string): EventoEtapa => ({ job_id: 'job-1', etapa: etapaNome, status })

describe('calcularProgresso', () => {
  it.each(['geracao_codigo', 'extracao_parametros'])(
    'mostra a espera pelo provedor em %s, sem tratá-la como erro',
    (nome) => {
      const progresso = calcularProgresso('gerando_regra', etapa(nome, 'aguardando_provedor'))

      expect(progresso.detalhe).toBe(MENSAGEM_DE_ESPERA_DO_PROVEDOR)
      expect(progresso.erro).toBe(false)
    },
  )

  it('volta ao texto da etapa quando o próximo evento de progresso chega', () => {
    const progresso = calcularProgresso('gerando_regra', etapa('geracao_codigo', 'iniciada'))

    expect(progresso.detalhe).toBe('Preparando a regra para a simulação.')
  })

  it('a mensagem de espera usa só conceitos do usuário', () => {
    for (const proibido of ['gerando_regra', 'geracao_codigo', 'aguardando_provedor', '503', 'gemini', 'google', 'etapa']) {
      expect(MENSAGEM_DE_ESPERA_DO_PROVEDOR.toLowerCase()).not.toContain(proibido)
    }
  })
})
