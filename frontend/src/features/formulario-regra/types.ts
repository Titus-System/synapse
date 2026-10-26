export interface OpcaoDeVigencia {
  valor: string
  rotulo: string
}

export interface FormularioDeRegra {
  vigenciaInicio: string
  vigenciaFim: string
  loja: string[]
  marca: string[]
  cargo: string[]
  todasLojas: boolean
  todasMarcas: boolean
  todosCargos: boolean
  modoTaxa: 'uniforme' | 'porCargo' | 'uniformeComExcecoes'
  taxasPorCargo: { cargo: string; percentual: string }[]
  percentual: string
  orcamento: string
  metaVenda: string
}

export type CampoDoFormulario = Exclude<
  keyof FormularioDeRegra,
  'todasLojas' | 'todasMarcas' | 'todosCargos' | 'modoTaxa'
>
