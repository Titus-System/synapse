import { apiClient } from '@/services/api'
import type { JobResumo, PaginaJobs, SituacaoListagem, Job } from '@/types/api'

export function listarPaginaDoHistorico(
  situacao: SituacaoListagem,
  pagina: number,
  tamanho: number,
  signal?: AbortSignal,
): Promise<PaginaJobs> {
  return apiClient.listarJobs({ situacao, pagina, tamanho }, signal)
}

export function consultarRegraDoHistorico(id: string, signal?: AbortSignal): Promise<Job> {
  return apiClient.consultarJob(id, signal)
}

export async function listarTodosOsJobs(signal?: AbortSignal): Promise<JobResumo[]> {
  const resumosDosJobs: JobResumo[] = []
  let numeroDaPagina = 0
  let totalDeJobs = 0
  let itensDaPagina: JobResumo[] = []

  do {
    const paginaDeJobs = await apiClient.listarJobs(
      { pagina: numeroDaPagina, tamanho: 100 },
      signal,
    )
    totalDeJobs = paginaDeJobs.total
    itensDaPagina = paginaDeJobs.itens
    resumosDosJobs.push(...itensDaPagina)
    numeroDaPagina += 1
  } while (resumosDosJobs.length < totalDeJobs && itensDaPagina.length > 0)

  return resumosDosJobs
}
