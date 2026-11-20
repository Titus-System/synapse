import { onScopeDispose, ref, shallowRef } from 'vue'
import { HttpError } from '@/services/http'
export function useConsultaAuditoria<T>(
  operacao:
    | 'listar_dossies'
    | 'consultar_dossie'
    | 'listar_eventos_auditoria'
    | 'consultar_filtros_auditoria'
    | 'listar_trilha_dossie'
    | 'consultar_resumo_dossie',
) {
  const dados = shallowRef<T>()
  const carregando = ref(false)
  const erro = ref('')
  let controle: AbortController | undefined
  async function carregar(consulta: (signal: AbortSignal) => Promise<T>, jobId?: string) {
    controle?.abort()
    const atual = new AbortController()
    controle = atual
    dados.value = undefined
    erro.value = ''
    carregando.value = true
    const inicio = performance.now()
    try {
      const resposta = await consulta(atual.signal)
      if (!atual.signal.aborted) {
        dados.value = resposta
        registrar('sucesso')
      }
    } catch (falha) {
      if (atual.signal.aborted) return
      const codigo =
        falha instanceof HttpError &&
        ['sem_permissao', 'job_nao_encontrado', 'nao_autenticado', 'requisicao_invalida'].includes(
          falha.code ?? '',
        )
          ? falha.code
          : 'indisponivel'
      erro.value =
        codigo === 'sem_permissao'
          ? 'Acesso negado. Esta área é exclusiva para auditores.'
          : codigo === 'job_nao_encontrado'
            ? 'Dossiê não encontrado.'
            : codigo === 'requisicao_invalida'
              ? 'Não foi possível consultar com estes critérios. Revise-os e tente novamente.'
              : 'Não foi possível carregar os registros. Tente novamente.'
      registrar('falha', codigo)
    } finally {
      if (controle === atual) carregando.value = false
    }
    function registrar(resultado: 'sucesso' | 'falha', codigo?: string) {
      const linha = JSON.stringify({
        timestamp: new Date().toISOString(),
        level: resultado === 'falha' ? 'ERROR' : 'INFO',
        message: 'Consulta de auditoria concluída',
        'service.name': 'synapse-frontend',
        ...(jobId ? { job_id: jobId } : {}),
        extra: { operacao, resultado, codigo, duracao_ms: performance.now() - inicio },
      })
      if (resultado === 'falha') console.error(linha)
      else console.info(linha)
    }
  }
  onScopeDispose(() => controle?.abort())
  return { dados, carregando, erro, carregar }
}
