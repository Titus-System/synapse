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

export interface SimulacaoLigada {
  numero: number
  simulacao: SimulacaoAuditoria
  resultado?: ResultadoAuditoria
  versao?: VersaoAuditoria
  codigo?: CodigoAuditoria
  comparacao?: ComparacaoSimulacao
}

const ACOES_DE_FECHAMENTO = ['confirmar_liberar', 'salvar', 'arquivar', 'cancelar']

export function ligarSimulacoes(
  registro: RegistroAuditoria,
  comparacoes: ComparacaoSimulacao[] = [],
): SimulacaoLigada[] {
  return [...registro.simulacoes]
    .sort((a, b) => Date.parse(a.criado_em) - Date.parse(b.criado_em))
    .map((simulacao, indice) => ({
      numero: indice + 1,
      simulacao,
      resultado: registro.resultados.find((r) => r.id === simulacao.resultado_id),
      versao: registro.versoes.find((v) => v.id === simulacao.regra_id),
      codigo: registro.codigos.find((c) => c.id === simulacao.codigo_gerado_id),
      comparacao: comparacoes.find((c) => c.resultado_id === simulacao.resultado_id),
    }))
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