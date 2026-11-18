import { describe, expect, it } from 'vitest'
import { montarConversa } from './useConversaAuditoria'
import { registroExemplo } from './registroAuditoria.fixture'

describe('montarConversa', () => {
  it('ordena entrada, conflitos, correção, versões e códigos pelo registro', () => {
    const itens = montarConversa(registroExemplo)
    expect(itens.map((i) => i.tipo)).toEqual([
      'entrada', // 14:00 entrada inicial
      'chamada', // 14:01 extração
      'versao', // 14:03 v1
      'conflitos', // 14:04
      'entrada', // 14:05 correção
      'chamada', // 14:05 extração da correção
      'versao', // 14:07 v2
      'chamada', // 14:07 geração de código
      'codigo', // 14:09
    ])
  })

  it('liga a correção à rodada pelo horário e confere pelo texto', () => {
    const correcao = montarConversa(registroExemplo).filter((i) => i.tipo === 'entrada')[1]
    expect(correcao).toMatchObject({ tipo: 'entrada', rodada: 1 })
  })

  it('não liga a entrada inicial a nenhuma rodada', () => {
    const inicial = montarConversa(registroExemplo)[0]
    expect(inicial).toMatchObject({ tipo: 'entrada', rodada: undefined })
  })

  it('deixa a correção sem ligação quando nenhuma rodada tem o mesmo horário', () => {
    const registro = structuredClone(registroExemplo)
    registro.rodadas[0]!.correcao!.enviada_em = '2025-11-28T15:00:00Z'
    const correcao = montarConversa(registro).filter((i) => i.tipo === 'entrada')[1]
    expect(correcao).toMatchObject({ rodada: undefined })
  })

  it('informa o número da versão de cada código', () => {
    const codigo = montarConversa(registroExemplo).find((i) => i.tipo === 'codigo')
    expect(codigo).toMatchObject({ versao: 2 })
  })

  it('desempata horários iguais: versão antes da chamada seguinte não se aplica, entrada antes da chamada', () => {
    const itens = montarConversa(registroExemplo)
    const i = itens.findIndex((x) => x.tipo === 'entrada' && x.instante === '2025-11-28T14:05:00Z')
    expect(itens[i + 1]?.tipo).toBe('chamada')
  })

  it('põe a extração antes da versão e a geração de código depois, em horário igual', () => {
    const registro = structuredClone(registroExemplo)
    const instante = '2025-11-28T14:07:00Z'
    registro.chamadas_modelo.forEach((c) => (c.criado_em = '2025-11-28T13:00:00Z'))
    registro.chamadas_modelo[0]!.criado_em = instante // extracao_parametros
    registro.chamadas_modelo[2]!.criado_em = instante // geracao_codigo
    const nos = montarConversa(registro)
        .filter((i) => i.instante === instante)
        .map((i) => (i.tipo === 'chamada' ? i.chamada.no : i.tipo))
    expect(nos).toEqual(['extracao_parametros', 'versao', 'geracao_codigo'])
  })
})