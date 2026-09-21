import { describe, expect, it } from 'vitest'
import {
  transformarRegra,
  transformarResultado,
} from './transformarRegra'
import type {
  RepresentacaoRegra,
  ResultadoSimulacao,
} from '@/types/api'

describe('transformarRegra', () => {
  it('transforma o núcleo da regra', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {
        vigencia: {
          inicio: '2025-11',
          fim: '2025-11',
        },
        loja: ['13'],
        marca: ['10'],
        cargo: ['100'],
        percentual: 0.025,
      },
      especificacoes: [],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado).toEqual({
      se: [
        'vigência = 11/2025',
        'loja = 13',
        'marca = 10',
        'cargo = 100',
        '% de comissionamento = 2.5%',
      ],
      entao: [],
    })
  })

  it('transforma uma faixa de valor com bônus fixo', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.1',
          construto: 'faixa_valor',
          limite_inferior: 40000,
          limite_superior: 50000,
          efeito: {
            tipo: 'bonus_fixo',
            valor: 3500,
          },
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'valor entre R$ 40.000,00 e R$ 50.000,00',
    ])

    expect(resultado.entao).toEqual([
      'bônus fixo = R$ 3.500,00',
    ])
  })

  it('transforma uma condição de limiar', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.2',
          construto: 'condicao_limiar',
          metrica: 'venda_total',
          escopo_agregacao: 'loja',
          operador: '>=',
          limiar: 50000,
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'venda total >= R$ 50.000,00',
    ])
  })

  it('transforma uma janela de datas com acréscimo percentual', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.2',
          construto: 'janela_datas',
          data_inicial: '2025-11-24',
          data_final: '2025-11-30',
          efeito: {
            tipo: 'acrescimo_pct',
            valor: 0.01,
          },
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'data entre 24/11/2025 e 30/11/2025',
    ])

    expect(resultado.entao).toEqual([
      'acréscimo = 1%',
    ])
  })

  it('transforma uma exclusão', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.3',
          construto: 'exclusao',
          dimensao: 'cargo',
          valores: ['150', '200'],
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'excluir cargo = 150, 200',
    ])
  })

  it('transforma um bônus fixo', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.4',
          construto: 'bonus_fixo',
          alvo: {
            tipo: 'lista',
            valor: ['MATRIC-1', 'MATRIC-2'],
          },
          valor: 500,
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.entao).toEqual([
      'bônus fixo = R$ 500,00',
    ])
  })

  it('transforma uma regra genérica', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.6',
          construto: 'generico',
          descricao: 'dobrar a comissão no aniversário da loja',
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'dobrar a comissão no aniversário da loja',
    ])
  })

  it('preserva a ordem das especificações', () => {
    const representacao: RepresentacaoRegra = {
      nucleo: {},
      especificacoes: [
        {
          ref: 'elem.1',
          construto: 'condicao_limiar',
          metrica: 'venda_total',
          escopo_agregacao: 'loja',
          operador: '>=',
          limiar: 50000,
        },
        {
          ref: 'elem.2',
          construto: 'exclusao',
          dimensao: 'cargo',
          valores: ['150'],
        },
        {
          ref: 'elem.3',
          construto: 'bonus_fixo',
          alvo: {
            tipo: 'lista',
            valor: ['MATRIC-1'],
          },
          valor: 500,
        },
      ],
    }

    const resultado = transformarRegra(representacao)

    expect(resultado.se).toEqual([
      'venda total >= R$ 50.000,00',
      'excluir cargo = 150',
    ])

    expect(resultado.entao).toEqual([
      'bônus fixo = R$ 500,00',
    ])
  })
})

describe('transformarResultado', () => {
  it('transforma os totais da simulação quando o orçamento é respeitado', () => {
    const resultado: ResultadoSimulacao = {
      totais: {
        baseline: 10000,
        simulado: 12000,
        diferenca_abs: 2000,
        diferenca_pct: 0.2,
        orcamento: 15000,
      },
      assercoes: [],
      decomposicao: {},
    }

    expect(transformarResultado(resultado)).toEqual([
      'comissão = R$ 12.000,00',
      'orçamento = OK',
    ])
  })

  it('indica quando o valor simulado ultrapassa o orçamento', () => {
    const resultado: ResultadoSimulacao = {
      totais: {
        baseline: 10000,
        simulado: 18000,
        diferenca_abs: 8000,
        diferenca_pct: 0.8,
        orcamento: 15000,
      },
      assercoes: [],
      decomposicao: {},
    }

    expect(transformarResultado(resultado)).toEqual([
      'comissão = R$ 18.000,00',
      'orçamento = Ultrapassado',
    ])
  })
})