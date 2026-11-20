import { describe, expect, it } from 'vitest'
import { finalizacaoDoDossie, ligarSimulacoes } from './simulacoesDossie'
import { registroExemplo } from './registroAuditoria.fixture'
import type { ComparacaoSimulacao, RegistroAuditoria } from '../types'

const totais = { baseline: 1, simulado: 2, diferenca_abs: 1, diferenca_pct: 1 }
const indicador = { anterior: 1, atual: 2, variacao: 1 }

function registroComTres(): RegistroAuditoria {
  const r = structuredClone(registroExemplo)
  const regra = r.versoes[1]!.id
  const codigo = r.codigos[0]!.id
  const status = ['erro_codigo', 'sucesso', 'sucesso'] as const
  r.resultados = status.map((s, i) => ({
    id: `res-${i + 1}`,
    codigo_gerado_id: codigo,
    status: s,
    proposito: 'simulacao' as const,
    totais: s === 'sucesso' ? totais : null,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  r.simulacoes = status.map((_, i) => ({
    id: `sim-${i + 1}`,
    regra_id: regra,
    codigo_gerado_id: codigo,
    resultado_id: `res-${i + 1}`,
    flag_baixa_rastreabilidade: false,
    criado_em: `2025-11-28T14:1${i}:00Z`,
  }))
  return r
}
const comparacao: ComparacaoSimulacao = {
  resultado_id: 'res-3',
  resultado_anterior_id: 'res-2',
  baseline: indicador,
  simulado: indicador,
  diferenca_abs: indicador,
  diferenca_pct: indicador,
}

describe('ligarSimulacoes', () => {
  it('numera pela ordem de criação e liga resultado, versão e código', () => {
    const lista = ligarSimulacoes(registroComTres(), [comparacao])
    expect(lista.map((s) => s.numero)).toEqual([1, 2, 3])
    expect(lista[0]!.resultado?.status).toBe('erro_codigo')
    expect(lista[0]!.versao?.versao).toBe(2)
    expect(lista[0]!.codigo?.id).toBe(registroExemplo.codigos[0]!.id)
  })

  it('liga a comparação só à simulação 3', () => {
    const lista = ligarSimulacoes(registroComTres(), [comparacao])
    expect(lista.map((s) => s.comparacao !== undefined)).toEqual([false, false, true])
    expect(lista[2]!.comparacao?.resultado_anterior_id).toBe('res-2')
  })

  it('deixa a simulação com falha sem totais', () => {
    expect(ligarSimulacoes(registroComTres())[0]!.resultado?.totais).toBeNull()
  })

  it('tolera simulação sem resultado', () => {
    const r = registroComTres()
    delete r.simulacoes[0]!.resultado_id
    expect(ligarSimulacoes(r)[0]!.resultado).toBeUndefined()
  })
})

describe('parâmetros da simulação', () => {
  it('na simulação com falha, usa os parâmetros da versão e a meta do resultado', () => {
    const r = registroComTres()
    r.versoes[1]!.parametros = { orcamento: 650000, competencias: ['2025-10', '2025-11'] }
    r.job.orcamento = 1
    r.resultados[0]!.meta_venda = 30000000
    expect(ligarSimulacoes(r)[0]!.parametros).toEqual({
      competencias: ['2025-10', '2025-11'],
      orcamento: 650000,
      meta_venda: 30000000,
    })
  })

  it('usa os do job quando a versão não grava parâmetros', () => {
    const r = registroComTres()
    delete r.versoes[1]!.parametros
    r.job.competencias = ['2025-09', '2025-10']
    r.job.orcamento = 500000
    const primeira = ligarSimulacoes(r)[0]!.parametros
    expect(primeira.competencias).toEqual(['2025-09', '2025-10'])
    expect(primeira.orcamento).toBe(500000)
  })

  it('usa os do job quando o texto não disse o período', () => {
    const r = registroComTres()
    r.versoes[1]!.parametros = { orcamento: 600000 }
    r.job.competencias = ['2025-08', '2025-09']
    expect(ligarSimulacoes(r)[0]!.parametros.competencias).toEqual(['2025-08', '2025-09'])
  })

  it('com sucesso, o orçamento é o aplicado na execução', () => {
    const r = registroComTres()
    expect(ligarSimulacoes(r)[1]!.parametros.orcamento).toBeUndefined()
    r.resultados[1]!.totais = { ...totais, orcamento: 640000 }
    expect(ligarSimulacoes(r)[1]!.parametros.orcamento).toBe(640000)
  })

  it('sem resultado, a meta vem da versão', () => {
    const r = registroComTres()
    delete r.simulacoes[0]!.resultado_id
    expect(ligarSimulacoes(r)[0]!.parametros.meta_venda).toBe(28000000)
  })
})

describe('finalizacaoDoDossie', () => {
  it('usa a última ação de fechamento e ignora aceitar_meta', () => {
    const r = structuredClone(registroExemplo)
    r.acoes = [
      { id: 'a1', acao: 'salvar', executado_em: '2025-11-28T14:18:00Z' },
      { id: 'a2', acao: 'aceitar_meta', executado_em: '2025-11-28T14:19:00Z' },
    ]
    expect(finalizacaoDoDossie(r)?.acao.acao).toBe('salvar')
  })

  it('traz o aceite da meta quando houver e é indefinida sem fechamento', () => {
    const r = structuredClone(registroExemplo)
    r.acoes = [{ id: 'a1', acao: 'arquivar', executado_em: '2025-11-28T14:18:00Z' }]
    r.sugestoes_meta = [
      { regra_id: 'x', criada_em: '2025-11-28T14:16:00Z', aceita_em: '2025-11-28T14:17:00Z' },
    ]
    expect(finalizacaoDoDossie(r)?.aceite?.aceita_em).toBe('2025-11-28T14:17:00Z')
    r.acoes = []
    expect(finalizacaoDoDossie(r)).toBeUndefined()
  })
})