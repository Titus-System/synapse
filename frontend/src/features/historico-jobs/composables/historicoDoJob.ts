import type { Job, RegraVersionada } from '@/types/api'
import { regraMaisRecente } from '@/services/job'

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
