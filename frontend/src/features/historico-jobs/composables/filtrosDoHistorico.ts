import type { JobResumo } from '@/types/api'

export type Ordenacao = 'recentes' | 'antigas' | 'nome-asc' | 'nome-desc'
export type Periodo = 'todos' | '7d' | '30d' | '90d' | '12m'

export interface FiltrosDoHistorico {
  busca: string
  ordenacao: Ordenacao
  periodo: Periodo
  // Datas do campo `<input type="date">`, no formato AAAA-MM-DD; vazio desliga o limite.
  criadaDesde: string
  criadaAte: string
  competencias: string[]
}

export const OPCOES_DE_ORDENACAO: { valor: Ordenacao; rotulo: string }[] = [
  { valor: 'recentes', rotulo: 'Mais recentes primeiro' },
  { valor: 'antigas', rotulo: 'Mais antigas primeiro' },
  { valor: 'nome-asc', rotulo: 'Nome (A–Z)' },
  { valor: 'nome-desc', rotulo: 'Nome (Z–A)' },
]

export const OPCOES_DE_PERIODO: { valor: Periodo; rotulo: string }[] = [
  { valor: 'todos', rotulo: 'Todos os períodos' },
  { valor: '7d', rotulo: 'Últimos 7 dias' },
  { valor: '30d', rotulo: 'Últimos 30 dias' },
  { valor: '90d', rotulo: 'Últimos 90 dias' },
  { valor: '12m', rotulo: 'Últimos 12 meses' },
]

export function filtrosIniciais(): FiltrosDoHistorico {
  return {
    busca: '',
    ordenacao: 'recentes',
    periodo: 'todos',
    criadaDesde: '',
    criadaAte: '',
    competencias: [],
  }
}

// O id do job é UUIDv7: o começo é o carimbo de tempo e repete entre regras próximas;
// o fim é aleatório e é o que diferencia uma regra da outra.
export function rotuloDaRegra(id: string, nome?: string | null): string {
  const numero = id.slice(-6).toUpperCase()
  const definido = nome?.trim()
  return definido ? `Regra ${numero} · ${definido}` : `Regra ${numero}`
}

export function formatarCompetencia(valor: string): string {
  const [ano, mes] = valor.split('-')
  return ano && mes ? `${mes}/${ano}` : valor
}

// Sem acento e sem caixa, para "comissao" achar "Comissão".
export function normalizarTexto(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

export function correspondeABusca(textos: string[], termoNormalizado: string): boolean {
  return textos.some((texto) => normalizarTexto(texto).includes(termoNormalizado))
}

export function quantidadeDeFiltrosAvancados(filtros: FiltrosDoHistorico): number {
  return (
    (filtros.criadaDesde ? 1 : 0) +
    (filtros.criadaAte ? 1 : 0) +
    (filtros.competencias.length ? 1 : 0)
  )
}

export function filtrando(filtros: FiltrosDoHistorico): boolean {
  return (
    filtros.busca.trim() !== '' ||
    filtros.periodo !== 'todos' ||
    quantidadeDeFiltrosAvancados(filtros) > 0
  )
}

export function competenciasDisponiveis(resumos: JobResumo[]): string[] {
  return [...new Set(resumos.flatMap((resumo) => resumo.competencias))].sort().reverse()
}

function inicioDoPeriodo(periodo: Periodo, agora: Date): Date | undefined {
  const inicio = new Date(agora)
  switch (periodo) {
    case 'todos':
      return undefined
    case '7d':
      inicio.setDate(inicio.getDate() - 7)
      return inicio
    case '30d':
      inicio.setDate(inicio.getDate() - 30)
      return inicio
    case '90d':
      inicio.setDate(inicio.getDate() - 90)
      return inicio
    case '12m':
      inicio.setMonth(inicio.getMonth() - 12)
      return inicio
  }
}

// AAAA-MM-DD do campo de data é um dia no fuso do navegador, não em UTC.
function diaLocal(valor: string, fimDoDia: boolean): Date | undefined {
  const [ano, mes, dia] = valor.split('-').map(Number)
  if (!ano || !mes || !dia) return undefined
  return fimDoDia ? new Date(ano, mes - 1, dia, 23, 59, 59, 999) : new Date(ano, mes - 1, dia)
}

// Filtra por período, datas e meses simulados e ordena. A busca por texto fica de fora
// porque depende dos detalhes de cada regra, carregados à parte.
export function filtrarEOrdenar(
  resumos: JobResumo[],
  filtros: FiltrosDoHistorico,
  nomeDe: (resumo: JobResumo) => string | null | undefined,
  agora: Date = new Date(),
): JobResumo[] {
  const limites = [
    inicioDoPeriodo(filtros.periodo, agora),
    filtros.criadaDesde ? diaLocal(filtros.criadaDesde, false) : undefined,
  ].filter((data): data is Date => data !== undefined)
  const fim = filtros.criadaAte ? diaLocal(filtros.criadaAte, true) : undefined

  const filtrados = resumos.filter((resumo) => {
    const criadaEm = new Date(resumo.criado_em)
    if (limites.some((inicio) => criadaEm < inicio)) return false
    if (fim && criadaEm > fim) return false
    return (
      filtros.competencias.length === 0 ||
      resumo.competencias.some((competencia) => filtros.competencias.includes(competencia))
    )
  })

  const porData = (a: JobResumo, b: JobResumo) => a.criado_em.localeCompare(b.criado_em)
  // Regra sem nome fica no fim nas duas direções, em vez de ordenar pelo número aleatório.
  const porNome = (sentido: 1 | -1) => (a: JobResumo, b: JobResumo) => {
    const nomeA = nomeDe(a)?.trim() ?? ''
    const nomeB = nomeDe(b)?.trim() ?? ''
    if (!nomeA || !nomeB) return Number(!nomeA) - Number(!nomeB)
    return sentido * nomeA.localeCompare(nomeB, 'pt-BR', { sensitivity: 'base' })
  }
  const comparar = {
    recentes: (a: JobResumo, b: JobResumo) => porData(b, a),
    antigas: porData,
    'nome-asc': porNome(1),
    'nome-desc': porNome(-1),
  }[filtros.ordenacao]
  return filtrados.sort(comparar)
}
