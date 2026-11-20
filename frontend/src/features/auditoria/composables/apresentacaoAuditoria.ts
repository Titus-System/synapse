import { formatarReais } from '@/composables/apresentacaoDetalhamento'
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
/** Data sem hora (AAAA-MM-DD) em pt-BR. Não passa por `Date`, que a leria como meia-noite UTC e a mostraria no dia anterior em Brasília. */
export function dataCivilAuditoria(valor: string): string {
  const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(valor)
  return partes ? `${partes[3]}/${partes[2]}/${partes[1]}` : valor
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
/** Fração (0,0778) como percentual pt-BR (7,78%). */
export function percentualAuditoria(fracao: number): string {
  return new Intl.NumberFormat('pt-BR', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(fracao)
}
/** Variação com sinal explícito; o valor já vem calculado do resumo. */
export function sinalAuditoria(texto: string, valor: number): string {
  return valor > 0 ? `+${texto}` : texto
}
// Sem `maximumFractionDigits`, o Intl arredonda em 3 casas: a taxa 0,0275 viraria 0,028.
const PERCENTUAL_SEM_CORTE = new Intl.NumberFormat('pt-BR', {
  style: 'percent',
  maximumFractionDigits: 20,
})
const NUMERO_SEM_CORTE = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 20 })
const PARTES_EM_REAIS = new Set(['nucleo.orcamento', 'nucleo.meta_venda'])
/** Valor de `anterior`/`novo` de uma alteração, formatado pelo tipo da parte; o resto como texto. */
export function valorDeAlteracao(ref: string, valor: unknown): string {
  if (valor === undefined) return '—'
  if (typeof valor === 'number') {
    if (ref === 'nucleo.percentual') return PERCENTUAL_SEM_CORTE.format(valor)
    if (PARTES_EM_REAIS.has(ref)) return formatarReais(valor)
    return NUMERO_SEM_CORTE.format(valor)
  }
  if (typeof valor === 'string') return valor
  return JSON.stringify(valor)
}
const SITUACAO_RESULTADO: Record<string, string> = {
  sucesso: 'Concluída',
  assercao_violada: 'Asserção violada',
  erro_codigo: 'Erro no código',
  erro_infra: 'Erro de infraestrutura',
}
export function situacaoDoResultado(status?: string): string {
  return status ? (SITUACAO_RESULTADO[status] ?? status) : 'Sem resultado'
}
const ACOES_FINALIZACAO: Record<string, string> = {
  confirmar_liberar: 'Confirmar e liberar',
  salvar: 'Salvar',
  arquivar: 'Arquivar',
  cancelar: 'Cancelar',
  aceitar_meta: 'Aceitar meta',
}
export function acaoDeFinalizacao(acao: string): string {
  return ACOES_FINALIZACAO[acao] ?? acao
}
const VEREDITOS: Record<string, string> = {
  viavel: 'Viável',
  inviavel: 'Inviável',
  indeterminado: 'Indeterminado',
}
export function vereditoAuditoria(veredito?: string | null): string {
  return veredito ? (VEREDITOS[veredito] ?? veredito) : 'Sem veredito'
}
/** Id longo (UUID e afins) vira um rótulo curto; o completo fica no title e na cópia. */
export function idCurto(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id
}
const CAMPOS_DA_REGRA: Record<string, string> = {
  'nucleo.orcamento': 'Orçamento',
  'nucleo.meta_venda': 'Meta de venda',
  'nucleo.competencias': 'Competências',
  'nucleo.percentual': 'Percentual de comissão',
  'nucleo.taxas_por_cargo': 'Taxas de comissão por cargo',
  'nucleo.vigencia': 'Vigência',
  'nucleo.loja': 'Lojas (códigos)',
  'nucleo.marca': 'Marcas (códigos)',
  'nucleo.cargo': 'Cargos (códigos)',
}
/** Nome legível de uma parte da regra; valor desconhecido aparece como veio. */
export function campoDaRegra(ref: string): string {
  const condicao = /^elem\.(\d+)$/.exec(ref)
  if (condicao) return `Condição ${condicao[1]}`
  return CAMPOS_DA_REGRA[ref] ?? ref
}
/** Itens em lista pt-BR: "2 e 3", "1, 2 e 3". */
export function listaAuditoria(itens: string[]): string {
  if (itens.length < 2) return itens.join('')
  return `${itens.slice(0, -1).join(', ')} e ${itens[itens.length - 1]}`
}
/** Vigência em competências (AAAA-MM), como se lê no Brasil. */
export function vigenciaAuditoria(vigencia?: { inicio: string; fim: string } | null): string {
  if (!vigencia) return 'Não informada'
  const inicio = mesAuditoria(vigencia.inicio)
  return vigencia.inicio === vigencia.fim ? inicio : `${inicio} a ${mesAuditoria(vigencia.fim)}`
}
// Só estilo do veredito que a API devolveu: viável em verde, inviável em vermelho.
const DESTAQUES_DO_VEREDITO: Record<string, string> = {
  viavel: 'bg-[#e4f2e7] text-[#22683a]',
  inviavel: 'bg-[#fde4e0] text-[#b42318]',
}
export function destaqueDoVeredito(veredito?: string | null): string {
  return (veredito && DESTAQUES_DO_VEREDITO[veredito]) || 'bg-[#fff0e9] text-[#2e1a10]'
}
