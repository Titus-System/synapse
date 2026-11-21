import { expect, it } from 'vitest'
import { eventoExemplo } from '../auditoria.fixture'
import {
  abaDoEvento,
  acaoDeFinalizacao,
  campoDaRegra,
  dataCivilAuditoria,
  destaqueDoVeredito,
  diaAuditoria,
  horaAuditoria,
  idCurto,
  listaAuditoria,
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
  vigenciaAuditoria,
} from './apresentacaoAuditoria'
import type { TipoEventoAuditoria } from '../types'
it('formata data sem hora no mesmo dia, sem converter fuso', () => {
  expect(dataCivilAuditoria('2026-11-01')).toBe('01/11/2026')
  expect(dataCivilAuditoria('01/11/2026')).toBe('01/11/2026')
})
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
  expect(valorDeAlteracao('elem.1', undefined)).toBe('—')
  expect(valorDeAlteracao('elem.1', 'abc')).toBe('abc')
  expect(valorDeAlteracao('nucleo.loja', ['13'])).toBe('["13"]')
})
it('formata a alteração pelo tipo da parte, sem arredondar a taxa', () => {
  expect(valorDeAlteracao('nucleo.percentual', 0.0275)).toBe('2,75%')
  expect(valorDeAlteracao('nucleo.percentual', 0.123456789)).toBe('12,3456789%')
  expect(valorDeAlteracao('nucleo.orcamento', 650000)).toBe('R$ 650.000,00')
  expect(valorDeAlteracao('nucleo.meta_venda', 28000000)).toBe('R$ 28.000.000,00')
  expect(valorDeAlteracao('nucleo.campo_novo', 0.0275)).toBe('0,0275')
})
it('rotula situação, veredito e ação, com o valor cru como reserva', () => {
  expect(situacaoDoResultado('erro_codigo')).toBe('Erro no código')
  expect(situacaoDoResultado()).toBe('Sem resultado')
  expect(vereditoAuditoria('viavel')).toBe('Viável')
  expect(vereditoAuditoria(null)).toBe('Sem veredito')
  expect(acaoDeFinalizacao('salvar')).toBe('Salvar')
  expect(acaoDeFinalizacao('nova')).toBe('nova')
})
it('dá nome legível às partes da regra e mantém o desconhecido como veio', () => {
  expect(campoDaRegra('nucleo.meta_venda')).toBe('Meta de venda')
  expect(campoDaRegra('nucleo.orcamento')).toBe('Orçamento')
  expect(campoDaRegra('elem.2')).toBe('Condição 2')
  expect(campoDaRegra('nucleo.campo_novo')).toBe('nucleo.campo_novo')
})
it('abrevia só ids longos', () => {
  expect(idCurto('0bbc1cae-da75-5fe0-ab91-52240a99454c')).toBe('0bbc1cae…')
  expect(idCurto('sim-1')).toBe('sim-1')
})
it('junta itens como lista em português', () => {
  expect(listaAuditoria(['2'])).toBe('2')
  expect(listaAuditoria(['2', '3'])).toBe('2 e 3')
  expect(listaAuditoria(['1', '2', '3'])).toBe('1, 2 e 3')
})
it('formata a vigência em competências', () => {
  expect(vigenciaAuditoria({ inicio: '2025-11', fim: '2025-11' })).toBe('11/2025')
  expect(vigenciaAuditoria({ inicio: '2025-10', fim: '2025-12' })).toBe('10/2025 a 12/2025')
  expect(vigenciaAuditoria(null)).toBe('Não informada')
})
it('estiliza o destaque pelo veredito que a API devolveu', () => {
  expect(destaqueDoVeredito('viavel')).toContain('bg-[#e4f2e7]')
  expect(destaqueDoVeredito('inviavel')).toContain('bg-[#fde4e0]')
  expect(destaqueDoVeredito('indeterminado')).toContain('bg-[#fff0e9]')
  expect(destaqueDoVeredito(undefined)).toContain('bg-[#fff0e9]')
})
