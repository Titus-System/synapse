import { nomesDoEscopo } from '@/services/catalogoRh'
import { percentuaisDoNucleo, vigenciaDoNucleo } from '@/composables/apresentacaoNucleo'
import type { NucleoRegra } from '@/types/api'

export interface ParametroConversa {
  rotulo: string
  valor: string
}

// Vocabulário do backlog (DEC-084): canal = loja, equipes = cargo.
export function parametrosDaRegra(
  nucleo: NucleoRegra,
  metaVenda?: number,
  competencias?: string[],
): ParametroConversa[] {
  return [
    { rotulo: 'Validade', valor: vigenciaDoNucleo(nucleo, competencias) },
    { rotulo: 'Marca', valor: nomesDoEscopo('marca', nucleo.marca) },
    { rotulo: 'Canal', valor: nomesDoEscopo('loja', nucleo.loja) },
    { rotulo: 'Equipes', valor: nomesDoEscopo('cargo', nucleo.cargo) },
    {
      rotulo: 'Comissionamento',
      valor: percentuaisDoNucleo(nucleo),
    },
    {
      rotulo: 'Meta de vendas',
      valor:
        metaVenda == null
          ? 'Não informada'
          : `R$ ${metaVenda.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    },
  ]
}
