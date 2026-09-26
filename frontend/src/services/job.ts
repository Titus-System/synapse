import type { Job, RegraVersionada } from '@/types/api'

export function regraMaisRecente(regras: readonly RegraVersionada[]): RegraVersionada | undefined {
  return regras.reduce<RegraVersionada | undefined>(
    (atual, regra) => (!atual || regra.versao > atual.versao ? regra : atual),
    undefined,
  )
}

export function simulacaoVisivel(job: Job | null) {
  if (
    !job ||
    [
      'aguardando_transcricao',
      'aguardando_confirmacao_parametros',
      'gerando_regra',
      'simulando',
    ].includes(job.status)
  ) {
    return null
  }
  return job.simulacao ?? null
}
