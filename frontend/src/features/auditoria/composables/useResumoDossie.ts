import { auditoriaApi } from '../services/auditoria.api'
import type { ResumoDossie } from '../types'
import { useConsultaAuditoria } from './useConsultaAuditoria'

export function useResumoDossie() {
  const { dados, carregando, erro, carregar } =
    useConsultaAuditoria<ResumoDossie>('consultar_resumo_dossie')
  function consultar(id: string) {
    return carregar((signal) => auditoriaApi.obterResumo(id, signal), id)
  }
  return { resumo: dados, carregando, erro, consultar }
}