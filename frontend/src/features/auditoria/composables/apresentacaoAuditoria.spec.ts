import { expect, it } from 'vitest'
import { eventoExemplo } from '../auditoria.fixture'
import {
  abaDoEvento,
  acaoDeFinalizacao,
  diaAuditoria,
  horaAuditoria,
  mesAuditoria,
  percentualAuditoria,
  quemFezOEvento,
  seloDoStatus,
  sinalAuditoria,
  situacaoDoEvento,
  situacaoDoResultado,
  tipoDoEvento,
  valorDeAlteracao,
  vereditoAuditoria,
} from './apresentacaoAuditoria'
import type { TipoEventoAuditoria } from '../types'
it.each([
  ['resultado_simulacao', 'simulacoes'],
  ['sugestao_meta_criada', 'simulacoes'],
  ['sugestao_meta_aceita', 'simulacoes'],
  ['acao_usuario', 'simulacoes'],
  ['job_erro', 'simulacoes'],
  ['entrada', 'conversa'],
  ['rodada_correcao', 'conversa'],
  ['codigo_gerado', 'conversa'],
  ['versao_regra', 'regra'],
] as [TipoEventoAuditoria, string][])('abre o evento %s na aba %s', (tipo, aba) => {
  expect(abaDoEvento(tipo)).toBe(aba)
})
it('descreve a situação com os campos que o evento trouxe', () => {
  expect(situacaoDoEvento(eventoExemplo())).toBe('Sucesso · Viável')
  expect(
    situacaoDoEvento(
      eventoExemplo({
        tipo: 'entrada',
        status: undefined,
        veredito: undefined,
        finalidade: 'correcao',
        tipo_entrada: 'voz',
      }),
    ),
  ).toBe('Correção · Voz')
  expect(
    situacaoDoEvento(
      eventoExemplo({
        tipo: 'versao_regra',
        status: null,
        veredito: null,
        versao: 2,
        origem_versao: 'origem_nova',
      }),
    ),
  ).toBe('v2 · origem_nova')
  expect(
    situacaoDoEvento(eventoExemplo({ tipo: 'codigo_gerado', status: null, veredito: null })),
  ).toBe('—')
})
it('nomeia o tipo e formata o mês como se lê no Brasil', () => {
  expect(tipoDoEvento('sugestao_meta_aceita')).toBe('Sugestão de meta aceita')
  expect(mesAuditoria('2026-11')).toBe('11/2026')
})
it('separa dia e hora no horário de Brasília', () => {
  expect(diaAuditoria('2026-12-01T02:30:00Z')).toBe('30/11/2026')
  expect(horaAuditoria('2026-12-01T02:30:00Z')).toBe('23:30:00')
})
it('atribui o evento ao dono do job só quando foi ato dele', () => {
  expect(quemFezOEvento(eventoExemplo({ autor: 'usuario' }))).toBe('rh.outro')
  expect(quemFezOEvento(eventoExemplo({ autor: 'sistema' }))).toBe('Sistema')
})
it('colore o selo pelo status que a API devolveu', () => {
  expect(seloDoStatus('liberado')).toContain('text-[#22683a]')
  expect(seloDoStatus('erro')).toContain('text-[#b42318]')
  expect(seloDoStatus('simulando')).toContain('text-[#644b3e]')
})
it('formata fração como percentual', () => {
  expect(percentualAuditoria(0.0778)).toBe('7,78%')
})
it('põe sinal só na variação positiva', () => {
  expect(sinalAuditoria('R$ 1,00', 1)).toBe('+R$ 1,00')
  expect(sinalAuditoria('R$ 0,00', 0)).toBe('R$ 0,00')
  expect(sinalAuditoria('-R$ 1,00', -1)).toBe('-R$ 1,00')
})
it('formata o valor de uma alteração sem inferir', () => {
  expect(valorDeAlteracao(undefined)).toBe('—')
  expect(valorDeAlteracao(650000)).toBe('650.000')
  expect(valorDeAlteracao('abc')).toBe('abc')
  expect(valorDeAlteracao(['2025-11'])).toBe('["2025-11"]')
})
it('rotula situação, veredito e ação, com o valor cru como reserva', () => {
  expect(situacaoDoResultado('erro_codigo')).toBe('Erro no código')
  expect(situacaoDoResultado()).toBe('Sem resultado')
  expect(vereditoAuditoria('viavel')).toBe('Viável')
  expect(vereditoAuditoria(null)).toBe('Sem veredito')
  expect(acaoDeFinalizacao('salvar')).toBe('Salvar')
  expect(acaoDeFinalizacao('nova')).toBe('nova')
})