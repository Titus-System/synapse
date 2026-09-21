import type {
  EspecificacaoRegra,
  RepresentacaoRegra,
  ResultadoSimulacao,
} from '@/types/api'

export interface RegraFormatada {
  se: string[]
  entao: string[]
}

interface EfeitoRegra {
  tipo: string
  valor: number
}

interface FaixaValor extends EspecificacaoRegra {
  construto: 'faixa_valor'
  limite_inferior: number
  limite_superior: number
  efeito: EfeitoRegra
}

interface CondicaoLimiar extends EspecificacaoRegra {
  construto: 'condicao_limiar'
  metrica: string
  escopo_agregacao: 'matricula' | 'loja' | 'marca' | 'rede'
  operador: '>=' | '>' | '<=' | '<' | '=='
  limiar: number
}

interface JanelaDatas extends EspecificacaoRegra {
  construto: 'janela_datas'
  data_inicial: string
  data_final: string
  efeito: EfeitoRegra
}

interface Exclusao extends EspecificacaoRegra {
  construto: 'exclusao'
  dimensao: 'loja' | 'marca' | 'cargo'
  valores: string[]
}

interface BonusFixo extends EspecificacaoRegra {
  construto: 'bonus_fixo'
  alvo: {
    tipo: 'lista' | 'filtro'
    valor: unknown
  }
  valor: number
}

interface Generico extends EspecificacaoRegra {
  construto: 'generico'
  descricao: string
  campos?: Record<string, unknown>
}

export function transformarRegra(
  representacao: RepresentacaoRegra,
): RegraFormatada {
  const se: string[] = []
  const entao: string[] = []

  adicionarNucleo(se, representacao)

  for (const elemento of representacao.especificacoes) {
    switch (elemento.construto) {
      case 'faixa_valor':
        adicionarFaixaValor(
          elemento as FaixaValor,
          se,
          entao,
        )
        break

      case 'condicao_limiar':
        adicionarCondicaoLimiar(
          elemento as CondicaoLimiar,
          se,
        )
        break

      case 'janela_datas':
        adicionarJanelaDatas(
          elemento as JanelaDatas,
          se,
          entao,
        )
        break

      case 'exclusao':
        adicionarExclusao(
          elemento as Exclusao,
          se,
        )
        break

      case 'bonus_fixo':
        adicionarBonusFixo(
          elemento as BonusFixo,
          entao,
        )
        break

      case 'generico':
        adicionarGenerico(
          elemento as Generico,
          se,
        )
        break

      default:
        se.push(elemento.construto)
        break
    }
  }

  return {
    se,
    entao,
  }
}

export function transformarResultado(
  resultado: ResultadoSimulacao,
): string[] {
  return [
    `comissão = ${formatarMoeda(resultado.totais.simulado)}`,
    `orçamento = ${
      resultado.totais.simulado <= resultado.totais.orcamento
        ? 'OK'
        : 'Ultrapassado'
    }`,
  ]
}

function adicionarNucleo(
  se: string[],
  representacao: RepresentacaoRegra,
): void {
  const { nucleo } = representacao

  if (nucleo.vigencia) {
    const { inicio, fim } = nucleo.vigencia

    if (inicio === fim) {
      se.push(`vigência = ${formatarCompetencia(inicio)}`)
    } else {
      se.push(
        `vigência = ${formatarCompetencia(inicio)} até ${formatarCompetencia(fim)}`,
      )
    }
  }

  if (nucleo.loja?.length) {
    se.push(`loja = ${nucleo.loja.join(', ')}`)
  }

  if (nucleo.marca?.length) {
    se.push(`marca = ${nucleo.marca.join(', ')}`)
  }

  if (nucleo.cargo?.length) {
    se.push(`cargo = ${nucleo.cargo.join(', ')}`)
  }

  if (nucleo.percentual != null) {
    se.push(
      `% de comissionamento = ${formatarPercentual(nucleo.percentual)}`,
    )
  }
}

function adicionarFaixaValor(
  elemento: FaixaValor,
  se: string[],
  entao: string[],
): void {
  se.push(
    `valor entre ${formatarMoeda(elemento.limite_inferior)} e ${formatarMoeda(elemento.limite_superior)}`,
  )

  entao.push(formatarEfeito(elemento.efeito))
}

function adicionarCondicaoLimiar(
  elemento: CondicaoLimiar,
  se: string[],
): void {
  se.push(
    `${formatarMetrica(elemento.metrica)} ${elemento.operador} ${formatarValorLimiar(elemento.limiar)}`,
  )
}

function adicionarJanelaDatas(
  elemento: JanelaDatas,
  se: string[],
  entao: string[],
): void {
  se.push(
    `data entre ${formatarData(elemento.data_inicial)} e ${formatarData(elemento.data_final)}`,
  )

  entao.push(formatarEfeito(elemento.efeito))
}

function adicionarExclusao(
  elemento: Exclusao,
  se: string[],
): void {
  se.push(
    `excluir ${elemento.dimensao} = ${elemento.valores.join(', ')}`,
  )
}

function adicionarBonusFixo(
  elemento: BonusFixo,
  entao: string[],
): void {
  entao.push(
    `bônus fixo = ${formatarMoeda(elemento.valor)}`,
  )
}

function adicionarGenerico(
  elemento: Generico,
  se: string[],
): void {
  se.push(elemento.descricao)
}

function formatarEfeito(efeito: EfeitoRegra): string {
  switch (efeito.tipo) {
    case 'bonus_fixo':
      return `bônus fixo = ${formatarMoeda(efeito.valor)}`

    case 'acrescimo_pct':
      return `acréscimo = ${formatarPercentual(efeito.valor)}`

    default:
      return `${efeito.tipo} = ${efeito.valor}`
  }
}

function formatarCompetencia(valor: string): string {
  const [ano, mes] = valor.split('-')

  if (!ano || !mes) {
    return valor
  }

  return `${mes}/${ano}`
}

function formatarData(valor: string): string {
  const [ano, mes, dia] = valor.split('-')

  if (!ano || !mes || !dia) {
    return valor
  }

  return `${dia}/${mes}/${ano}`
}

function formatarPercentual(valor: number): string {
  return `${valor * 100}%`
}

function formatarMoeda(valor: number): string {
  return `R$ ${valor.toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatarMetrica(valor: string): string {
  return valor.replaceAll('_', ' ')
}

function formatarValorLimiar(valor: number): string {
  return formatarMoeda(valor)
}