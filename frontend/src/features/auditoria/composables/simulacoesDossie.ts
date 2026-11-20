import type {
  AcaoAuditoria,
  CodigoAuditoria,
  ComparacaoSimulacao,
  RegistroAuditoria,
  ResultadoAuditoria,
  SimulacaoAuditoria,
  SugestaoMetaAuditoria,
  VersaoAuditoria,
} from '../types'

export interface ParametrosSimulacao {
  competencias: string[]
  orcamento?: number
  meta_venda?: number
}

export interface SimulacaoLigada {
  numero: number
  simulacao: SimulacaoAuditoria
  resultado?: ResultadoAuditoria
  versao?: VersaoAuditoria
  codigo?: CodigoAuditoria
  comparacao?: ComparacaoSimulacao
  parametros: ParametrosSimulacao
}

const ACOES_DE_FECHAMENTO = ['confirmar_liberar', 'salvar', 'arquivar', 'cancelar']

/**
 * O resultado guarda a entrada que a execução usou: o orçamento em `totais`, que só existe
 * com `sucesso`, e a meta em qualquer status, nula quando a execução usou as vendas
 * históricas. Sem ela valem os parâmetros da versão e, onde a versão não os grava
 * (formulário, reprocessamento ou texto que não disse o parâmetro), os do job.
 */
function parametrosDaSimulacao(
  registro: RegistroAuditoria,
  versao?: VersaoAuditoria,
  resultado?: ResultadoAuditoria,
): ParametrosSimulacao {
  const daVersao = versao?.parametros
  return {
    competencias: daVersao?.competencias ?? registro.job.competencias,
    orcamento:
      resultado?.status === 'sucesso'
        ? resultado.totais?.orcamento
        : (daVersao?.orcamento ?? registro.job.orcamento),
    meta_venda: resultado ? resultado.meta_venda : (daVersao?.meta_venda ?? registro.job.meta_venda),
  }
}

export function ligarSimulacoes(
  registro: RegistroAuditoria,
  comparacoes: ComparacaoSimulacao[] = [],
): SimulacaoLigada[] {
  return [...registro.simulacoes]
    .sort((a, b) => Date.parse(a.criado_em) - Date.parse(b.criado_em))
    .map((simulacao, indice) => {
      const resultado = registro.resultados.find((r) => r.id === simulacao.resultado_id)
      const versao = registro.versoes.find((v) => v.id === simulacao.regra_id)
      return {
        numero: indice + 1,
        simulacao,
        resultado,
        versao,
        codigo: registro.codigos.find((c) => c.id === simulacao.codigo_gerado_id),
        comparacao: comparacoes.find((c) => c.resultado_id === simulacao.resultado_id),
        parametros: parametrosDaSimulacao(registro, versao, resultado),
      }
    })
}

export interface Finalizacao {
  acao: AcaoAuditoria
  aceite?: SugestaoMetaAuditoria
}

/** A última ação de fechamento registrada e, se houver, a sugestão de meta aceita. */
export function finalizacaoDoDossie(registro: RegistroAuditoria): Finalizacao | undefined {
  const acao = [...registro.acoes]
    .filter((a) => ACOES_DE_FECHAMENTO.includes(a.acao))
    .sort((a, b) => Date.parse(b.executado_em) - Date.parse(a.executado_em))[0]
  if (!acao) return undefined
  return { acao, aceite: registro.sugestoes_meta.find((s) => s.aceita_em) }
}