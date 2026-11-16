import type { RegistroAuditoria } from './types'
export function registroExemplo(): RegistroAuditoria {
  return {
    job: {
      id: 'job-1',
      nome: 'Comissão de novembro',
      status: 'liberado',
      origem: 'texto',
      competencias: ['2026-11'],
      criado_em: '2026-11-03T12:00:00Z',
      usuario: { login: 'rh.outro', nome: 'Outro usuário' },
    },
    entradas: [
      {
        id: 'entrada-1',
        tipo: 'texto',
        finalidade: 'entrada_inicial',
        criado_em: '2026-11-03T12:00:00Z',
        texto: '<img src=x onerror=alert(1)>',
      },
    ],
    versoes: [
      {
        id: 'regra-1',
        versao: 1,
        origem: 'extracao',
        criada_em: '2026-11-03T12:01:00Z',
        hash: 'abc',
        representacao: {
          nucleo: { loja: ['13'], marca: ['10'], cargo: ['100'], percentual: 0.03 },
          especificacoes: [],
        },
      },
    ],
    etapas: [
      {
        id: 'etapa-1',
        no: 'extracao_parametros',
        concluido_em: '2026-11-03T12:01:00Z',
        conclusao: {},
        regra_id: 'regra-1',
        submissao_id: 'entrada-1',
      },
    ],
    codigos: [
      {
        id: 'codigo-1',
        regra_id: 'regra-1',
        linguagem: 'python',
        fonte: 'fonte confidencial',
        prompt_id: 'prompt-1',
        criado_em: '2026-11-03T12:02:00Z',
      },
    ],
    rodadas: [],
    chamadas_modelo: [],
    resultados: [],
    simulacoes: [],
    transicoes: [],
    acoes: [],
    sugestoes_meta: [],
    explicacoes: [],
  }
}
