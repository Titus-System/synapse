import { http } from '@/services/http'
import type { StatusJob } from '@/types/api'

interface SubmissaoCriada {
  id: string
  job: { id: string; status: StatusJob }
}

export function enviarTexto(texto: string, signal: AbortSignal) {
  return http.post<SubmissaoCriada, object>(
    '/submissoes',
    {
      finalidade: 'entrada_inicial',
      tipo: 'texto',
      texto,
    },
    signal,
  )
}

export function enviarAudio(audio: Blob, signal: AbortSignal) {
  const corpo = new FormData()
  corpo.append('audio', audio, 'gravacao')
  corpo.append(
    'parametros',
    new Blob(
      [
        JSON.stringify({
          finalidade: 'entrada_inicial',
          tipo: 'voz',
        }),
      ],
      { type: 'application/json' },
    ),
  )
  return http.post<SubmissaoCriada, FormData>('/submissoes', corpo, signal)
}
