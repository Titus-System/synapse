import { expect, it } from 'vitest'
import { eventoExemplo } from '../auditoria.fixture'
import {
  abaDoEvento,
  diaAuditoria,
  horaAuditoria,
  mesAuditoria,
  quemFezOEvento,
  seloDoStatus,
  situacaoDoEvento,
  tipoDoEvento,
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
