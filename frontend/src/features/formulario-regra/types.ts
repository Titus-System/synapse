export interface OpcaoDeVigencia {
  valor: string
  rotulo: string
}

export interface OpcaoDeCodigo {
  valor: string
  rotulo: string
}

export interface FormularioDeRegra {
  vigenciaInicio: string
  vigenciaFim: string
  loja: string[]
  marca: string[]
  cargo: string[]
  percentual: string
  orcamento: string
}

export type CampoDoFormulario = keyof FormularioDeRegra
