import type { EventoEtapa, StatusJob } from '@/types/api'

export interface ProgressoSimulacao {
  percentual: number
  titulo: string
  detalhe: string
  erro: boolean
}

const etapas: Record<string, { percentual: number; titulo: string; detalhe: string }> = {
  extracao_parametros: { percentual: 20, titulo: 'Interpretando a regra', detalhe: 'Extraindo os parâmetros da sua solicitação.' },
  validacao_dominio: { percentual: 30, titulo: 'Validando os parâmetros', detalhe: 'Conferindo se a regra pode ser processada.' },
  confirmacao: { percentual: 35, titulo: 'Aguardando confirmação', detalhe: 'Revise os parâmetros sugeridos para continuar.' },
  geracao_codigo: { percentual: 45, titulo: 'Gerando o código da regra', detalhe: 'Preparando a regra para a simulação.' },
  delegacao_worker: { percentual: 65, titulo: 'Preparando a simulação', detalhe: 'Enviando a regra para execução segura.' },
  interpretacao_resultado: { percentual: 85, titulo: 'Interpretando o resultado', detalhe: 'Consolidando os dados calculados.' },
  decisao: { percentual: 95, titulo: 'Concluindo a simulação', detalhe: 'Registrando a decisão do processamento.' },
  sugestao_adaptacao: { percentual: 70, titulo: 'Procurando uma alternativa', detalhe: 'Ajustando a regra para caber no orçamento.' },
  explicacao: { percentual: 95, titulo: 'Concluindo a simulação', detalhe: 'Preparando a explicação do resultado.' },
}

const statusBase: Record<StatusJob, { percentual: number; titulo: string; detalhe: string; erro?: boolean }> = {
  aguardando_transcricao: { percentual: 10, titulo: 'Preparando a solicitação', detalhe: 'Aguardando a transcrição do conteúdo.' },
  aguardando_confirmacao_parametros: { percentual: 35, titulo: 'Aguardando confirmação', detalhe: 'Revise os parâmetros sugeridos para continuar.' },
  gerando_regra: { percentual: 40, titulo: 'Gerando a regra', detalhe: 'Transformando sua solicitação em uma regra estruturada.' },
  simulando: { percentual: 75, titulo: 'Executando a simulação', detalhe: 'Calculando o impacto sobre os dados históricos.' },
  simulacao_inviavel: { percentual: 100, titulo: 'Simulação concluída', detalhe: 'A regra não atende aos critérios de viabilidade.' },
  aguardando_decisao_usuario: { percentual: 100, titulo: 'Simulação concluída', detalhe: 'O resultado está pronto para sua decisão.' },
  liberado: { percentual: 100, titulo: 'Regra liberada', detalhe: 'A regra foi liberada com sucesso.' },
  cancelado: { percentual: 100, titulo: 'Processamento cancelado', detalhe: 'Este processamento foi cancelado.' },
  arquivado: { percentual: 100, titulo: 'Processamento arquivado', detalhe: 'Este processamento foi arquivado.' },
  erro: { percentual: 100, titulo: 'Processamento interrompido', detalhe: 'Não foi possível concluir esta simulação.', erro: true },
}

export function calcularProgresso(status: StatusJob | null, etapa: EventoEtapa | null): ProgressoSimulacao {
  const base = status ? statusBase[status] : null
  const etapaConhecida = etapa ? etapas[etapa.etapa] : undefined

  if (etapaConhecida && status === 'gerando_regra') {
    return { ...etapaConhecida, erro: etapa?.status === 'erro' }
  }

  if (base) return { ...base, erro: base.erro ?? false }

  return { percentual: 0, titulo: 'Conectando ao processamento', detalhe: 'Aguardando os primeiros eventos do job.', erro: false }
}
