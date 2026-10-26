import type { NucleoRegra, RepresentacaoRegra } from '@/types/api'

export function percentuaisDoNucleo(nucleo?: NucleoRegra): string {
  return percentuaisDaRegra({ nucleo: nucleo ?? {}, especificacoes: [] })
}

export function percentuaisDaRegra(regra?: RepresentacaoRegra): string {
  const nucleo = regra?.nucleo
  const valores = [
    nucleo?.percentual,
    ...(nucleo?.taxas_por_cargo?.map((taxa) => taxa.percentual) ?? []),
  ]
  for (const elemento of regra?.especificacoes ?? []) {
    if (elemento.construto !== 'faixa_valor' && elemento.construto !== 'janela_datas') continue
    const efeito = elemento.efeito
    if (efeito == null || typeof efeito !== 'object') continue
    if (
      'tipo' in efeito &&
      (efeito.tipo === 'substituicao_pct' || efeito.tipo === 'acrescimo_pct') &&
      'valor' in efeito &&
      typeof efeito.valor === 'number'
    )
      valores.push(efeito.valor)
  }
  const formato = new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 20 })
  return (
    [...new Set(valores.filter((valor): valor is number => valor != null))]
      .map((valor) => formato.format(valor))
      .join(', ') || 'Não informado'
  )
}

export function vigenciaDoNucleo(nucleo?: NucleoRegra, competencias?: string[]): string {
  const formatar = (valor: string) => valor.split('-').reverse().join('/')
  if (nucleo?.vigencia) {
    const { inicio, fim } = nucleo.vigencia
    return inicio === fim ? formatar(inicio) : `${formatar(inicio)} até ${formatar(fim)}`
  }
  return competencias?.length
    ? competencias.map(formatar).join(', ')
    : 'Todo o período da simulação (competências não disponíveis)'
}
