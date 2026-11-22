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

// A busca, a ordenação e os filtros da tela rodam no navegador e precisam da lista inteira.
export async function listarHistoricoCompleto(
  situacao: SituacaoListagem,
  signal?: AbortSignal,
): Promise<{ itens: JobResumo[]; total: number }> {
  const itens: JobResumo[] = []
  let numero = 0
  let total = 0
  let pagina: PaginaJobs
  do {
    pagina = await apiClient.listarJobs({ situacao, pagina: numero, tamanho: 100 }, signal)
    total = pagina.total
    itens.push(...pagina.itens)
    numero += 1
  } while (itens.length < total && pagina.itens.length > 0)
  return { itens, total }
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
