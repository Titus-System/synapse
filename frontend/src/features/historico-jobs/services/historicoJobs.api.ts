import { apiClient } from '@/services/api'
import type { JobResumo } from '@/types/api'

export async function listarTodosOsJobs(signal?: AbortSignal): Promise<JobResumo[]> {
  const resumosDosJobs: JobResumo[] = []
  let numeroDaPagina = 0
  let totalDeJobs = 0
  let itensDaPagina: JobResumo[] = []

  do {
    const paginaDeJobs = await apiClient.listarJobs({ pagina: numeroDaPagina, tamanho: 100 }, signal)
    totalDeJobs = paginaDeJobs.total
    itensDaPagina = paginaDeJobs.itens
    resumosDosJobs.push(...itensDaPagina)
    numeroDaPagina += 1
  } while (resumosDosJobs.length < totalDeJobs && itensDaPagina.length > 0)

  return resumosDosJobs
}
