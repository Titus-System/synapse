import type { RepresentacaoRegra, ResultadoLinhas } from '@/types/api'
import { organizarLinhas } from '@/composables/apresentacaoDetalhamento'

export interface FiltrosRelatorio {
  loja: string[]
  marca: string[]
  cargo: string[]
  competencia: string[]
  matricula: string
}
export const filtrosVazios = (): FiltrosRelatorio => ({
  loja: [],
  marca: [],
  cargo: [],
  competencia: [],
  matricula: '',
})

export function linhasDoEscopo(
  linhas: ResultadoLinhas,
  regra?: RepresentacaoRegra,
  competencias?: string[],
) {
  const nucleo = regra?.nucleo
  return organizarLinhas(linhas).filter((linha) => {
    for (const dimensao of ['loja', 'marca', 'cargo'] as const) {
      const escopo = nucleo?.[dimensao]
      if (escopo?.length && !escopo.includes(linha[`cod_${dimensao}`])) return false
    }
    if (nucleo?.vigencia)
      return linha.competencia >= nucleo.vigencia.inicio && linha.competencia <= nucleo.vigencia.fim
    return !competencias?.length || competencias.includes(linha.competencia)
  })
}

export function filtrarLinhas(
  linhas: ReturnType<typeof organizarLinhas>,
  filtros: FiltrosRelatorio,
) {
  return linhas.filter(
    (linha) =>
      (['loja', 'marca', 'cargo'] as const).every(
        (dimensao) =>
          !filtros[dimensao].length || filtros[dimensao].includes(linha[`cod_${dimensao}`]),
      ) &&
      (!filtros.competencia.length || filtros.competencia.includes(linha.competencia)) &&
      linha.matricula
        .toLocaleLowerCase('pt-BR')
        .includes(filtros.matricula.toLocaleLowerCase('pt-BR')),
  )
}
