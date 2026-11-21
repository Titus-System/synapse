import type { LocationQuery, LocationQueryRaw } from 'vue-router'
import type { CampoFiltroEventos, FiltroEventos, FiltroPainel } from '../types'
/** Valor do mês no endereço quando o auditor escolhe todos os meses; sem `mes`, vale o corrente. */
export const TODOS_OS_MESES = 'todos'
const CAMPOS: CampoFiltroEventos[] = ['usuario', 'mes', 'loja', 'marca', 'cargo', 'regra']
function primeiro(valor: LocationQuery[string] | undefined): string {
  const texto = Array.isArray(valor) ? valor[0] : valor
  return typeof texto === 'string' ? texto.trim() : ''
}
/** O mês corrente em Brasília, no formato AAAA-MM que o filtro `mes` da API recebe. */
export function mesCorrente(agora = new Date()): string {
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(agora)
  const parte = (tipo: 'year' | 'month') => partes.find((item) => item.type === tipo)?.value
  return `${parte('year')}-${parte('month')}`
}
export function filtroDaRota(query: LocationQuery, agora?: Date): FiltroPainel {
  const filtro = Object.fromEntries(
    CAMPOS.map((campo) => [campo, primeiro(query[campo])]),
  ) as FiltroPainel
  if (!filtro.mes) filtro.mes = mesCorrente(agora)
  return filtro
}
export function paginaDaRota(query: LocationQuery): number {
  const pagina = Number(primeiro(query.pagina))
  return Number.isInteger(pagina) && pagina > 0 ? pagina : 0
}
/** O endereço guarda o mês sempre, para que "todos os meses" não volte ao mês corrente. */
export function queryDoFiltro(filtro: FiltroPainel, pagina = 0): LocationQueryRaw {
  const query: LocationQueryRaw = {}
  for (const campo of CAMPOS) {
    const valor = filtro[campo].trim()
    if (valor) query[campo] = valor
  }
  if (pagina > 0) query.pagina = String(pagina)
  return query
}
export function consultaDoFiltro(filtro: FiltroPainel): FiltroEventos {
  const consulta: FiltroEventos = {}
  for (const campo of CAMPOS) {
    const valor = filtro[campo].trim()
    if (valor && !(campo === 'mes' && valor === TODOS_OS_MESES)) consulta[campo] = valor
  }
  return consulta
}
