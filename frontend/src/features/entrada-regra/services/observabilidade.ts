export function registrarEntrada(
  operacao: 'gravar_audio' | 'enviar_texto' | 'enviar_audio',
  resultado: 'sucesso' | 'falha' | 'cancelado',
  inicio: number,
  jobId?: string,
) {
  const registro = JSON.stringify({
    timestamp: new Date().toISOString(),
    level: resultado === 'falha' ? 'ERROR' : 'INFO',
    message: 'Operação de entrada da regra concluída',
    'service.name': 'synapse-frontend',
    ...(jobId ? { job_id: jobId } : {}),
    extra: { operacao, resultado, duracao_ms: performance.now() - inicio },
  })
  if (resultado === 'falha') console.error(registro)
  else console.info(registro)
}
