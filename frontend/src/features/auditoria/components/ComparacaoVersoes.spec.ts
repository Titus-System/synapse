import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ComparacaoVersoes from './ComparacaoVersoes.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import type { VersaoResumo } from '../types'

const versoes: VersaoResumo[] = [
  { id: 'v1', numero: 1, alteracoes: [] },
  {
    id: 'v2',
    numero: 2,
    regra_origem_id: 'v1',
    alteracoes: [
      { elemento_ref: 'nucleo.orcamento', anterior: 600000, novo: 650000 },
      { elemento_ref: 'elem.1', novo: 'bônus' },
      { elemento_ref: 'elem.2', anterior: 'exclusão' },
    ],
  },
]
const montar = (v = versoes) =>
  mount(ComparacaoVersoes, { props: { versoes: v, registradas: registroExemplo.versoes } })

describe('ComparacaoVersoes', () => {
  it('mostra só as partes alteradas, com anterior e novo', () => {
    const w = montar()
    expect(w.findAll('[data-alteracao]')).toHaveLength(3)
    const linha = w.get('[data-alteracao="nucleo.orcamento"]').text()
    expect(linha).toContain('600.000')
    expect(linha).toContain('650.000')
    expect(w.text()).toContain('entre v1 e v2')
  })

  it('marca parte incluída e removida', () => {
    const w = montar()
    expect(w.get('[data-alteracao="elem.1"]').text()).toContain('Incluída')
    expect(w.get('[data-alteracao="elem.2"]').text()).toContain('Removida')
  })

  it('mostra o nome legível do campo e guarda o ref original no title', () => {
    const w = montar()
    const campo = w.get('[data-alteracao="nucleo.orcamento"] td')
    expect(campo.text()).toContain('Orçamento')
    expect(campo.text()).not.toContain('nucleo.orcamento')
    expect(campo.attributes('title')).toBe('nucleo.orcamento')
    expect(w.get('[data-alteracao="elem.1"] td').text()).toContain('Condição 1')
  })

  it('não oferece a versão raiz para comparar', () => {
    const w = montar()
    expect(w.findAll('option')).toHaveLength(1)
  })

  it('informa quando a versão não teve alterações', () => {
    const w = montar([
      { id: 'v1', numero: 1, alteracoes: [] },
      { id: 'v2', numero: 2, regra_origem_id: 'v1', alteracoes: [] },
    ])
    expect(w.text()).toContain('Nenhuma parte alterada')
    expect(w.find('table').exists()).toBe(false)
  })

  it('informa quando só existe a versão raiz', () => {
    const w = montar([{ id: 'v1', numero: 1, alteracoes: [] }])
    expect(w.text()).toContain('Nenhuma versão com origem')
  })
})