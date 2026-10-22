import { expect, it } from 'vitest'
import { percentuaisDaRegra, vigenciaDoNucleo } from './apresentacaoNucleo'
import { nomesDoEscopo, nomeDaEntidade } from '@/services/catalogoRh'
it('apresenta taxas e efeitos estruturados na ordem, sem limiares, bônus ou números de texto livre', () => {
  expect(
    percentuaisDaRegra({
      nucleo: {
        percentual: 0,
        taxas_por_cargo: [
          { cargo: '100', percentual: 0.025 },
          { cargo: '200', percentual: 0.03 },
          { cargo: '150', percentual: 0.025 },
        ],
      },
      especificacoes: [
        {
          ref: 'elem.1',
          construto: 'faixa_valor',
          efeito: { tipo: 'substituicao_pct', valor: 0.0425 },
        },
        {
          ref: 'elem.2',
          construto: 'janela_datas',
          efeito: { tipo: 'acrescimo_pct', valor: 0.01 },
        },
        { ref: 'elem.3', construto: 'condicao_limiar', limiar: 0.8 },
        {
          ref: 'elem.4',
          construto: 'generico',
          descricao: '95% no texto livre',
          efeito: { tipo: 'acrescimo_pct', valor: 0.95 },
        },
        { ref: 'elem.5', construto: 'faixa_valor', efeito: { tipo: 'bonus_fixo', valor: 300 } },
      ],
    }),
  ).toBe('0%, 2,5%, 3%, 4,25%, 1%')
})
it('distingue ausência de taxa e preserva precisão sem inventar taxa média', () => {
  expect(percentuaisDaRegra()).toBe('Não informado')
  expect(percentuaisDaRegra({ nucleo: { percentual: 0.0123456789 }, especificacoes: [] })).toBe(
    '1,23456789%',
  )
})
it('usa apenas as competências reais do job como vigência e informa contexto ausente', () => {
  expect(vigenciaDoNucleo({}, ['2025-08', '2025-10'])).toBe('08/2025, 10/2025')
  expect(vigenciaDoNucleo({})).toContain('competências não disponíveis')
  expect(vigenciaDoNucleo({ vigencia: { inicio: '2025-11', fim: '2025-12' } })).toBe(
    '11/2025 até 12/2025',
  )
})
it('distingue ausência, declaração universal e nomes, sem normalizar códigos', () => {
  expect(nomesDoEscopo('loja')).toBe('Não informado')
  expect(nomesDoEscopo('loja', [])).toBe('Todas as lojas')
  expect(nomesDoEscopo('marca', ['10'])).toBe('PRETO')
  expect(nomeDaEntidade('cargo', '150')).toBe('GERENTE DE LOJA / GERENTE QUIOSQUE')
  expect(nomeDaEntidade('marca', '010')).toBe('Nome não disponível (código 010)')
  expect(nomeDaEntidade('cargo', '999')).toBe('Nome não disponível (código 999)')
})
