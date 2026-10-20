import type { NucleoRegra } from '@/types/api'

export interface ParametroConversa {
  rotulo: string
  valor: string
}

function competencia(valor: string): string {
  const [ano, mes] = valor.split('-')
  return ano && mes ? `${mes}/${ano}` : valor
}

function lista(valores: string[] | undefined): string {
  return valores?.length ? valores.join(', ') : 'Todos'
}

// Vocabulário do backlog (DEC-084): produto = marca, canal = loja, equipes = cargo.
export function parametrosDaRegra(nucleo: NucleoRegra, metaVenda?: number): ParametroConversa[] {
  const vigencia = nucleo.vigencia
  const validade = vigencia
    ? vigencia.inicio === vigencia.fim
      ? competencia(vigencia.inicio)
      : `${competencia(vigencia.inicio)} até ${competencia(vigencia.fim)}`
    : 'Todo o período'
  return [
    { rotulo: 'Validade', valor: validade },
    { rotulo: 'Produto', valor: lista(nucleo.marca) },
    { rotulo: 'Canal', valor: lista(nucleo.loja) },
    { rotulo: 'Equipes', valor: lista(nucleo.cargo) },
    { rotulo: 'Marcas', valor: lista(nucleo.marca) },
    {
      rotulo: 'Comissionamento',
      valor:
        nucleo.percentual == null
          ? 'Não informado'
          : `${(nucleo.percentual * 100).toLocaleString('pt-BR', { maximumFractionDigits: 2 })}%`,
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
