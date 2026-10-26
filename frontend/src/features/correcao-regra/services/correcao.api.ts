import { http } from '@/services/http'
import type { CorrecaoCriada, Rodada } from '../types'

export function listarRodadas(jobId: string, signal: AbortSignal) {
  return http.get<Rodada[]>(`/jobs/${encodeURIComponent(jobId)}/rodadas`, signal)
}
export function enviarCorrecaoTexto(jobId: string, texto: string, signal: AbortSignal) {
  return http.post<CorrecaoCriada, object>(
    '/submissoes',
    {
      finalidade: 'correcao',
      tipo: 'texto',
      job_id: jobId,
      texto,
    },
    signal,
  )
}
export function enviarCorrecaoVoz(jobId: string, audio: Blob, signal: AbortSignal) {
  const corpo = new FormData()
  corpo.append('audio', audio, 'gravacao')
  corpo.append(
    'parametros',
    new Blob([JSON.stringify({ finalidade: 'correcao', tipo: 'voz', job_id: jobId })], {
      type: 'application/json',
    }),
  )
  return http.post<CorrecaoCriada, FormData>('/submissoes', corpo, signal)
}
