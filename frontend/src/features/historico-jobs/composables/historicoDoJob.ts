import type { Job, RegraVersionada, Simulacao } from '@/types/api'
import { regraMaisRecente } from '@/services/job'

export function origemDaVersao(regra: RegraVersionada): string {
  const origens: Record<RegraVersionada['origem'], string> = {
    confirmacao_usuario: 'Formulário / confirmação',
    sugestao_adaptacao: 'Sugestão',
    reprocessamento: 'Reprocessamento',
    extracao: 'Extraída',
    correcao: 'Correção',
  }
  return origens[regra.origem]
}

export function versaoDeEncerramento(job: Job): RegraVersionada | undefined {
  return job.status === 'liberado'
    ? job.regras.find((regra) => regra.id === job.simulacao?.regra_id)
    : job.status === 'arquivado'
      ? regraMaisRecente(job.regras)
      : undefined
}
export function simulacoesDoHistorico(job: Job) {
  const simulacoes = [...(job.simulacoes ?? [])]
  if (job.simulacao && !simulacoes.some((item) => item.id === job.simulacao?.id))
    simulacoes.push(job.simulacao)
  return simulacoes
}

export function simulacaoAnterior(simulacao?: Simulacao): Simulacao | undefined {
  const anterior = simulacao?.anterior_a_meta_sugerida
  if (!simulacao || !anterior) return undefined
  return {
    ...anterior,
    id: simulacao.id,
    regra_id: simulacao.regra_id,
    flag_baixa_rastreabilidade: simulacao.flag_baixa_rastreabilidade,
  }
}
