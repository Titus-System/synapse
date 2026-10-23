import { HttpError } from '@/services/http'

type OperacaoConsulta = 'consultar_job' | 'consultar_detalhamento' | 'listar_jobs' | 'aceitar_meta'

export async function observarConsulta<T>(
  operacao: OperacaoConsulta,
  jobId: string,
  consultar: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  const inicio = performance.now()
  function registrar(resultado: 'iniciada' | 'sucesso' | 'falha' | 'cancelada', status?: number) {
    const registro = {
      timestamp: new Date().toISOString(),
      level: resultado === 'falha' ? 'WARN' : 'INFO',
      message:
        operacao === 'aceitar_meta' ? 'Ação do job no navegador' : 'Consulta do job no navegador',
      'service.name': 'synapse-frontend',
      job_id: jobId,
      extra: {
        operacao,
        resultado,
        ...(resultado === 'iniciada' ? {} : { duracao_ms: performance.now() - inicio }),
        ...(status == null ? {} : { status_http: status }),
      },
    }
    if (resultado === 'falha') console.warn(JSON.stringify(registro))
    else console.info(JSON.stringify(registro))
  }
  registrar('iniciada')
  try {
    const resposta = await consultar()
    registrar(signal?.aborted ? 'cancelada' : 'sucesso')
    return resposta
  } catch (erro) {
    const cancelada =
      signal?.aborted || (erro instanceof DOMException && erro.name === 'AbortError')
    registrar(
      cancelada ? 'cancelada' : 'falha',
      erro instanceof HttpError ? erro.status : undefined,
    )
    throw erro
  }
}
