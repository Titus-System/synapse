import type { RepresentacaoRegra, ResultadoLinhas } from '@/types/api'

export function organizarLinhas(linhas: ResultadoLinhas) {
  return Object.entries(linhas).flatMap(([competencia, colaboradores]) =>
    Object.entries(colaboradores).map(([matricula, linha]) => ({
      competencia,
      matricula,
      ...linha,
    })),
  )
}

export function formatarReais(valor: number): string {
  return `R$ ${valor.toLocaleString('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export interface RotuloContribuicao {
  rotulo: string
  descricao?: string
}

export function rotulosContribuicoes(
  regra: RepresentacaoRegra | undefined,
): Record<string, RotuloContribuicao> {
  const rotulos: Record<string, RotuloContribuicao> = {
    'nucleo.taxas_por_cargo': { rotulo: 'Taxas de comissão por cargo' },
    'nucleo.percentual': {
      rotulo:
        regra?.nucleo.percentual == null
          ? 'Percentual de comissão'
          : `Comissão de ${new Intl.NumberFormat('pt-BR', {
              style: 'percent',
              maximumFractionDigits: 4,
            }).format(regra.nucleo.percentual)}`,
    },
  }
  const nomes: Record<string, string> = {
    faixa_valor: 'Faixa de vendas',
    condicao_limiar: 'Condição de vendas',
    janela_datas: 'Período especial',
    exclusao: 'Exclusão da regra',
    bonus_fixo: 'Bônus fixo',
  }
  for (const [indice, elemento] of (regra?.especificacoes ?? []).entries()) {
    const nome = nomes[elemento.construto] ?? 'Condição adicional'
    let detalhe = ''
    if (elemento.construto === 'bonus_fixo' && typeof elemento.valor === 'number') {
      detalhe = ` de ${formatarReais(elemento.valor)}`
    } else if (
      elemento.construto === 'faixa_valor' &&
      typeof elemento.limite_inferior === 'number' &&
      typeof elemento.limite_superior === 'number'
    ) {
      detalhe = ` de ${formatarReais(elemento.limite_inferior)} a ${formatarReais(elemento.limite_superior)}`
    }
    // O texto de um genérico se repete em todas as linhas da tabela: fica fora do rótulo, para
    // ser aberto quando o usuário pedir.
    const descricao =
      elemento.construto === 'generico' && typeof elemento.descricao === 'string'
        ? elemento.descricao
        : undefined
    rotulos[elemento.ref] = { rotulo: `${nome}${detalhe} · condição ${indice + 1}`, descricao }
  }
  return rotulos
}
