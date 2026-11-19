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