import type { StatusJob } from '@/types/api'
import type { AbaDossie, EventoAuditoria, TipoEventoAuditoria } from '../types'
export function dataAuditoria(valor?: string): string {
  if (!valor) return 'Não registrada'
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'medium',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(valor))
}
export function codigosAuditoria(codigos?: string[]): string {
  return codigos?.length ? codigos.join(', ') : codigos ? 'Todos' : 'Não informado'
}
const TIPOS_DE_EVENTO: Record<TipoEventoAuditoria, string> = {
  entrada: 'Entrada',
  rodada_correcao: 'Rodada de correção',
  versao_regra: 'Versão da regra',
  codigo_gerado: 'Código gerado',
  resultado_simulacao: 'Simulação',
  sugestao_meta_criada: 'Sugestão de meta criada',
  sugestao_meta_aceita: 'Sugestão de meta aceita',
  acao_usuario: 'Ação do usuário',
  job_erro: 'Parada em erro',
}
// A aba do dossiê em que o registro de origem de cada evento aparece.
const ABAS_DO_EVENTO: Record<TipoEventoAuditoria, AbaDossie> = {
  entrada: 'conversa',
  rodada_correcao: 'conversa',
  codigo_gerado: 'conversa',
  versao_regra: 'regra',
  resultado_simulacao: 'simulacoes',
  sugestao_meta_criada: 'simulacoes',
  sugestao_meta_aceita: 'simulacoes',
  acao_usuario: 'simulacoes',
  job_erro: 'simulacoes',
}
const SITUACOES: Record<string, string> = {
  entrada_inicial: 'Entrada inicial',
  correcao: 'Correção',
  texto: 'Texto',
  voz: 'Voz',
  extracao: 'Extração',
  confirmacao_usuario: 'Confirmação do usuário',
  reprocessamento: 'Reprocessamento',
  sugestao_adaptacao: 'Sugestão de adaptação',
  sucesso: 'Sucesso',
  assercao_violada: 'Asserção violada',
  erro_codigo: 'Erro no código',
  erro_infra: 'Erro de infraestrutura',
  viavel: 'Viável',
  inviavel: 'Inviável',
  indeterminado: 'Indeterminado',
  confirmar_liberar: 'Confirmar e liberar',
  cancelar: 'Cancelar',
  salvar: 'Salvar',
  arquivar: 'Arquivar',
  aceitar_meta: 'Aceitar meta',
}
export function tipoDoEvento(tipo: TipoEventoAuditoria): string {
  return TIPOS_DE_EVENTO[tipo] ?? tipo
}
export function abaDoEvento(tipo: TipoEventoAuditoria): AbaDossie {
  return ABAS_DO_EVENTO[tipo] ?? 'regra'
}
export function autorDoEvento(autor: EventoAuditoria['autor']): string {
  return autor === 'usuario' ? 'Usuário' : 'Sistema'
}
/** Os campos de situação que o evento trouxe, na ordem do contrato; o vocabulário é aberto. */
export function situacaoDoEvento(evento: EventoAuditoria): string {
  const partes = [
    evento.finalidade,
    evento.tipo_entrada,
    evento.versao == null ? undefined : `v${evento.versao}`,
    evento.origem_versao,
    evento.status,
    evento.veredito,
    evento.acao,
  ].flatMap((valor) => (valor ? [SITUACOES[valor] ?? valor] : []))
  return partes.length ? partes.join(' · ') : '—'
}
export function mesAuditoria(mes: string): string {
  const [ano, numero] = mes.split('-')
  return ano && numero ? `${numero}/${ano}` : mes
}
const FUSO = 'America/Sao_Paulo'
export function diaAuditoria(valor: string): string {
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeZone: FUSO }).format(
    new Date(valor),
  )
}
export function horaAuditoria(valor: string): string {
  return new Intl.DateTimeFormat('pt-BR', { timeStyle: 'medium', timeZone: FUSO }).format(
    new Date(valor),
  )
}
const nosAuditoria: Record<string, string> = {
  extracao_parametros: 'Extração dos parâmetros',
  validacao_dominio: 'Validação da regra',
  confirmacao: 'Confirmação da correção',
  geracao_codigo: 'Geração do código',
  delegacao_worker: 'Envio para simulação',
  interpretacao_resultado: 'Interpretação do resultado',
  decisao: 'Decisão sobre o resultado',
  sugestao_adaptacao: 'Sugestão de adaptação',
  explicacao: 'Explicação do resultado',
}
export function nomeDoNo(no: string): string {
  return nosAuditoria[no] ?? no
}
const estadosDaRodada: Record<string, string> = {
  pendente: 'Aguardando correção',
  em_transcricao: 'Transcrevendo o áudio',
  em_reextracao: 'Interpretando a correção',
  reextracao_falhou: 'Falha ao aplicar a correção',
  corrigida: 'Corrigida',
  abandonada: 'Abandonada',
}
export function estadoDaRodada(estado: string): string {
  return estadosDaRodada[estado] ?? estado
}
/** Quem fez o evento: o dono do job quando foi ato dele, ou o sistema. */
export function quemFezOEvento(evento: EventoAuditoria): string {
  return evento.autor === 'usuario' ? evento.usuario_login : 'Sistema'
}
// Só estilo do status que a API devolveu: concluído em verde, parado em erro em vermelho.
const SELOS_DE_STATUS: Partial<Record<StatusJob, string>> = {
  liberado: 'bg-[#e4f2e7] text-[#22683a]',
  erro: 'bg-[#fde4e0] text-[#b42318]',
}
export function seloDoStatus(status: StatusJob): string {
  return SELOS_DE_STATUS[status] ?? 'bg-[#fff0e9] text-[#644b3e]'
}
