import { onScopeDispose, shallowRef, watch } from 'vue'
import { HttpError, type RespostaBinaria } from '@/services/http'
import type { AudioEntrada, AudiosEntradas } from '../types'

type CodigoAudio =
  | 'ok'
  | 'entrada_nao_encontrada'
  | 'job_nao_encontrado'
  | 'sem_permissao'
  | 'nao_autenticado'
  | 'requisicao_invalida'
  | 'falha_rede'
  | 'falha_servico'
  | 'tipo_invalido'
  | 'falha_reproducao'
  | 'falha_inesperada'

const codigosDaApi = new Set<string>([
  'entrada_nao_encontrada',
  'job_nao_encontrado',
  'sem_permissao',
  'nao_autenticado',
  'requisicao_invalida',
])

function codigoDaFalha(falha: unknown): CodigoAudio {
  if (!(falha instanceof HttpError)) return 'falha_inesperada'
  if (falha.code !== undefined && codigosDaApi.has(falha.code)) return falha.code as CodigoAudio
  if (falha.status === 0) return 'falha_rede'
  if (falha.status === 401) return 'nao_autenticado'
  if (falha.status === 403) return 'sem_permissao'
  if (falha.status >= 500) return 'falha_servico'
  return 'falha_inesperada'
}

function registrar(
  operacao: 'baixar_audio_entrada' | 'reproduzir_audio_entrada',
  codigo: CodigoAudio,
  jobId: string,
  entradaId: string,
  inicio?: number,
) {
  const nivel = codigo === 'ok' ? 'INFO' : codigo === 'entrada_nao_encontrada' ? 'WARN' : 'ERROR'
  const linha = JSON.stringify({
    timestamp: new Date().toISOString(),
    level: nivel,
    message:
      operacao === 'baixar_audio_entrada'
        ? 'Download do áudio da auditoria concluído'
        : 'Reprodução do áudio da auditoria falhou',
    'service.name': 'synapse-frontend',
    job_id: jobId,
    extra: {
      operacao,
      resultado: codigo === 'ok' ? 'sucesso' : 'falha',
      codigo,
      entrada_id: entradaId,
      ...(inicio === undefined ? {} : { duracao_ms: performance.now() - inicio }),
    },
  })
  if (nivel === 'ERROR') console.error(linha)
  else if (nivel === 'WARN') console.warn(linha)
  else console.info(linha)
}

/**
 * Baixa o áudio de uma entrada só quando o auditor pede para ouvi-lo, porque cada um chega a 5 MB.
 * A rota exige o token em memória, então o `<audio>` toca uma URL local do arquivo baixado, nunca a da rota.
 */
export function useAudiosEntradas(
  baixar: (entradaId: string, signal: AbortSignal) => Promise<RespostaBinaria>,
  jobId: () => string,
) {
  const audios = shallowRef<AudiosEntradas>({})
  const downloads = new Map<string, AbortController>()

  function definir(entradaId: string, audio: AudioEntrada) {
    audios.value = { ...audios.value, [entradaId]: audio }
  }

  async function ouvir(entradaId: string) {
    const estado = audios.value[entradaId]?.estado
    if (estado === 'carregando' || estado === 'pronto') return
    const controle = new AbortController()
    downloads.set(entradaId, controle)
    const job = jobId()
    const inicio = performance.now()
    definir(entradaId, { estado: 'carregando' })
    try {
      const { conteudo, tipo } = await baixar(entradaId, controle.signal)
      if (controle.signal.aborted) return
      if (!tipo.startsWith('audio/')) {
        definir(entradaId, { estado: 'erro' })
        registrar('baixar_audio_entrada', 'tipo_invalido', job, entradaId, inicio)
        return
      }
      definir(entradaId, { estado: 'pronto', url: URL.createObjectURL(conteudo) })
      registrar('baixar_audio_entrada', 'ok', job, entradaId, inicio)
    } catch (falha) {
      if (controle.signal.aborted) return
      const codigo = codigoDaFalha(falha)
      definir(entradaId, { estado: codigo === 'entrada_nao_encontrada' ? 'indisponivel' : 'erro' })
      registrar('baixar_audio_entrada', codigo, job, entradaId, inicio)
    } finally {
      if (downloads.get(entradaId) === controle) downloads.delete(entradaId)
    }
  }

  function falhouReproducao(entradaId: string) {
    const url = audios.value[entradaId]?.url
    if (url === undefined) return
    URL.revokeObjectURL(url)
    definir(entradaId, { estado: 'erro' })
    registrar('reproduzir_audio_entrada', 'falha_reproducao', jobId(), entradaId)
  }

  function limpar() {
    for (const controle of downloads.values()) controle.abort()
    downloads.clear()
    for (const audio of Object.values(audios.value))
      if (audio.url !== undefined) URL.revokeObjectURL(audio.url)
    audios.value = {}
  }

  watch(jobId, limpar)
  onScopeDispose(limpar)
  return { audios, ouvir, falhouReproducao, limpar }
}
