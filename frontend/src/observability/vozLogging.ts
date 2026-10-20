export type CodigoVoz =
  | 'ok'
  | 'cancelado'
  | 'sem_suporte'
  | 'permissao_negada'
  | 'sem_microfone'
  | 'microfone_indisponivel'
  | 'audio_vazio'
  | 'audio_muito_grande'
  | 'falha_gravacao'
  | 'audio_invalido'
  | 'estado_invalido'
  | 'requisicao_invalida'
  | 'nao_autenticado'
  | 'sem_permissao'
  | 'job_nao_encontrado'
  | 'falha_rede'
  | 'falha_servico'
  | 'reconectando'

export function registrarVoz(
  operacao:
    'gravar_audio' | 'enviar_correcao_voz' | 'enviar_correcao' | 'ler_rodadas' | 'conexao_correcao',
  codigo: CodigoVoz,
  inicio: number,
  jobId?: string,
) {
  const resultado = codigo === 'ok' ? 'sucesso' : codigo === 'cancelado' ? 'cancelado' : 'falha'
  const registro = JSON.stringify({
    timestamp: new Date().toISOString(),
    level: resultado === 'falha' ? 'ERROR' : 'INFO',
    message: 'Operação da interface concluída',
    'service.name': 'synapse-frontend',
    ...(jobId ? { job_id: jobId } : {}),
    extra: { operacao, codigo, resultado, duracao_ms: performance.now() - inicio },
  })
  if (resultado === 'falha') console.error(registro)
  else console.info(registro)
}
