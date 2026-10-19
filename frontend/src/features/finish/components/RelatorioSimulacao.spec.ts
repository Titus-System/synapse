import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { ResultadoLinhas } from '@/types/api'
import RelatorioSimulacao from './RelatorioSimulacao.vue'

const linha = (cod_loja: string) => ({
  cod_loja,
  cod_marca: '10',
  cod_cargo: '100',
  comissao_baseline: 10,
  comissao_simulada: 20,
  diferenca: 10,
  contribuicoes: {},
})
const linhas: ResultadoLinhas = {
  '2025-08': { 'ALPHA-1': linha('13'), 'BETA-2': linha('58') },
  '2025-09': { 'ALPHA-1': linha('58'), 'GAMMA-3': linha('13') },
}
const decomposicao = {
  matricula: { 'ALPHA-1': 9876.54, 'BETA-2': 123.45, 'GAMMA-3': 0 },
  loja_absoluto: { '13': 4567.89, '58': 5432.1, '99': 0 },
  competencia_absoluto: { '2025-08': 7890.12, '2025-09': 2109.87, '2025-10': 0 },
  loja: { ERRADA: 999 },
  competencia: { '1900-01': 999 },
}
function montar() {
  return mount(RelatorioSimulacao, {
    props: {
      aberto: true,
      carregando: false,
      erro: null,
      linhas,
      decomposicao,
    },
  })
}

it('filtra matrícula por trecho sem diferenciar maiúsculas e minúsculas e remove o filtro vazio', async () => {
  const wrapper = montar()
  await wrapper.get('input[type="search"]').setValue('lPhA')
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  expect(wrapper.get('tbody').text()).not.toContain('BETA')
  await wrapper.get('input').setValue('')
  expect(wrapper.findAll('tbody tr')).toHaveLength(4)
})

it.each([
  ['Loja', '58', ['BETA-2', 'ALPHA-1']],
  ['Competência', '2025-09', ['ALPHA-1', 'GAMMA-3']],
])('filtra por %s', async (nome, valor, esperadas) => {
  const wrapper = montar()
  const seletor = wrapper
    .findAll('label')
    .find((label) => label.text().startsWith(nome))!
    .get('select')
  await seletor.setValue(valor)
  expect(wrapper.findAll('tbody tr').map((tr) => tr.findAll('td')[1]!.text())).toEqual(esperadas)
})

it('combina os três filtros e limpa para restaurar a lista completa', async () => {
  const wrapper = montar()
  await wrapper.get('input').setValue('alpha')
  await wrapper.findAll('select')[0]!.setValue('58')
  await wrapper.findAll('select')[1]!.setValue('2025-09')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  expect(wrapper.get('tbody').text()).toContain('09/2025')
  expect(wrapper.get('tbody').text()).toContain('ALPHA-1')
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Limpar filtros')!
    .trigger('click')
  expect(wrapper.findAll('tbody tr')).toHaveLength(4)
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
  expect(
    wrapper.findAll('select').every((s) => (s.element as HTMLSelectElement).value === ''),
  ).toBe(true)
})

it('oferece exatamente as chaves das quebras absolutas, incluindo chaves sem linhas ou com zero', () => {
  const wrapper = montar()
  const valores = wrapper
    .findAll('select')
    .map((select) => select.findAll('option').map((option) => option.attributes('value')))
  expect(valores).toEqual([
    ['', '13', '58', '99'],
    ['', '2025-08', '2025-09', '2025-10'],
  ])
})

it('apresenta o estado sem resultado e mantém a limpeza acessível', async () => {
  const wrapper = montar()
  await wrapper.get('input').setValue('inexistente')
  expect(wrapper.text()).toContain('Nenhum registro encontrado para os filtros selecionados.')
  expect(wrapper.find('table').exists()).toBe(false)
  await wrapper
    .findAll('button')
    .find((b) => b.text() === 'Limpar filtros')!
    .trigger('click')
  expect(wrapper.findAll('tbody tr')).toHaveLength(4)
})

it('exibe os totais enviados pela API e não soma as linhas nem recalcula pelos filtros combinados', async () => {
  const wrapper = montar()
  const totais = wrapper.get('[aria-label="Totais da simulação"]')
  expect(totais.text()).toContain('R$ 9.876,54')
  expect(totais.text()).toContain('R$ 4.567,89')
  expect(totais.text()).toContain('R$ 7.890,12')
  expect(totais.text()).toContain('R$ 0,00')
  await wrapper.get('input').setValue('ALPHA')
  await wrapper.findAll('select')[0]!.setValue('58')
  await wrapper.findAll('select')[1]!.setValue('2025-09')
  expect(totais.text()).toContain('R$ 9.876,54')
  expect(totais.text()).toContain('R$ 5.432,10')
  expect(totais.text()).toContain('R$ 2.109,87')
  expect(totais.text()).not.toContain('R$ 123,45')
})

it('informa a ausência de totais sem substituir por diferenças ou valores calculados', async () => {
  const wrapper = montar()
  await wrapper.setProps({ decomposicao: { loja: { '13': 111 }, competencia: { '2025-08': 222 } } })
  expect(wrapper.get('[aria-label="Totais da simulação"]').text()).not.toMatch(/111|222/)
  expect(wrapper.findAll('details p')).toHaveLength(3)
  expect(wrapper.findAll('select').every((select) => select.findAll('option').length === 1)).toBe(
    true,
  )
})

it('mantém no máximo 25 linhas e volta à primeira página após trocar qualquer filtro', async () => {
  const wrapper = montar()
  const periodo = {
    '2025-08': Object.fromEntries(
      Array.from({ length: 2700 }, (_, i) => [`PESSOA-${i}`, linha('13')]),
    ),
  }
  await wrapper.setProps({ linhas: periodo })
  const proxima = () => wrapper.get('[aria-label="Páginas do relatório"]').findAll('button')[1]!
  await proxima().trigger('click')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 2')
  await wrapper.get('input').setValue('PESSOA')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 1')
  await proxima().trigger('click')
  await wrapper.findAll('select')[0]!.setValue('13')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 1')
  await proxima().trigger('click')
  await wrapper.findAll('select')[1]!.setValue('2025-08')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 1')
  expect(wrapper.findAll('tbody tr')).toHaveLength(25)
})
