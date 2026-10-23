import { HttpError } from '@/services/http'

export async function observarAceiteMeta<T>(jobId: string, executar: () => Promise<T>): Promise<T> {
  const inicio = performance.now()
  function registrar(resultado: 'iniciada' | 'sucesso' | 'falha' | 'conflito', status?: number) {
    const registro = JSON.stringify({
      timestamp: new Date().toISOString(),
      level: resultado === 'falha' || resultado === 'conflito' ? 'WARN' : 'INFO',
      message: 'Aceitação de meta no navegador',
      'service.name': 'synapse-frontend',
      job_id: jobId,
      extra: {
        operacao: 'aceitar_meta',
        resultado,
        ...(resultado === 'iniciada' ? {} : { duracao_ms: performance.now() - inicio }),
        ...(status == null ? {} : { status_http: status }),
      },
    })
    if (resultado === 'falha' || resultado === 'conflito') console.warn(registro)
    else console.info(registro)
  }
  registrar('iniciada')
  try {
    const resposta = await executar()
    registrar('sucesso')
    return resposta
  } catch (erro) {
    const status = erro instanceof HttpError ? erro.status : undefined
    registrar(status === 409 ? 'conflito' : 'falha', status)
    throw erro
  }
}
