export interface OpcaoDeCompetencia {
  valor: string
  rotulo: string
}

export interface FormularioDeRegra {
  vigenciaInicio: string
  vigenciaFim: string
  loja: string
  marca: string
  cargo: string
  percentual: string
  competencia: string
  orcamento: string
}

export type CampoDoFormulario = keyof FormularioDeRegra
