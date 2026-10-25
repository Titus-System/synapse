import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RelatorioSimulacao from './RelatorioSimulacao.vue'

const linha = {
  cod_loja: '13',
  cod_marca: '10',
  cod_cargo: '100',
  comissao_baseline: 10,
  comissao_simulada: 20,
  diferenca: 10,
  contribuicoes: {},
}
function montar() {
  return mount(RelatorioSimulacao, {
    props: {
      aberto: true,
      carregando: false,
      erro: null,
      linhas: { '2025-08': { 'ALPHA-1': linha, 'BETA-2': linha } },
      decomposicao: {
        matricula: { 'ALPHA-1': 9876.54 },
        loja_absoluto: { '13': 4567.89 },
        competencia_absoluto: { '2025-08': 7890.12 },
      },
    },
  })
}
it('mostra todas as linhas e os totais da API sem controles de filtro ou popup', () => {
  const wrapper = montar()
  expect(wrapper.find('input').exists()).toBe(false)
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.find('dialog').exists()).toBe(false)
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  expect(wrapper.text()).toContain('PRETO')
  expect(wrapper.text()).toContain('VENDEDOR LOJA')
  const totais = wrapper.get('[aria-label="Totais da simulação"]')
  expect(totais.text()).toContain('R$ 9.876,54')
  expect(totais.text()).toContain('R$ 4.567,89')
  expect(totais.text()).toContain('R$ 7.890,12')
  expect(wrapper.html().indexOf('Totais da Simulação')).toBeLessThan(
    wrapper.html().indexOf('<table'),
  )
})
it('mantém 25 linhas por página e reinicia ao trocar o resultado', async () => {
  const wrapper = montar()
  await wrapper.setProps({
    linhas: {
      '2025-08': Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`PESSOA-${i}`, linha])),
    },
  })
  expect(wrapper.findAll('tbody tr')).toHaveLength(25)
  await wrapper.get('[aria-label="Páginas do relatório"]').findAll('button')[1]!.trigger('click')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 2')
  await wrapper.setProps({ linhas: { '2025-09': { 'NOVA-PESSOA': linha } } })
  expect(wrapper.get('[role="status"]').text()).toContain('Página 1')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
})
it('distingue carregamento, falha recuperável e dados antigos sem detalhamento', async () => {
  const wrapper = montar()
  await wrapper.setProps({ carregando: true })
  expect(wrapper.get('[role="status"]').text()).toContain('Carregando')
  await wrapper.setProps({ carregando: false, erro: 'Falha segura' })
  expect(wrapper.get('[role="alert"]').text()).toContain('Falha segura')
  await wrapper.get('[role="alert"] button').trigger('click')
  expect(wrapper.emitted('tentarNovamente')).toHaveLength(1)
  await wrapper.setProps({ erro: null, linhas: undefined })
  expect(wrapper.text()).toContain('O detalhamento não está disponível')
})
it('informa ausência de agregados sem inferir totais das linhas', async () => {
  const wrapper = montar()
  await wrapper.setProps({ decomposicao: undefined })
  expect(wrapper.findAll('details p')).toHaveLength(3)
  expect(wrapper.get('[aria-label="Totais da simulação"]').text()).not.toContain('R$')
})
it('rola todas as colunas juntas, sem Competência e Matrícula fixas', () => {
  const wrapper = montar()
  const celulas = [
    ...wrapper.findAll('thead th').slice(0, 2),
    ...wrapper.findAll('tbody tr')[0]!.findAll('td').slice(0, 2),
  ]

  expect(celulas.map((celula) => celula.text())).toEqual([
    'Competência',
    'Matrícula',
    '08/2025',
    'ALPHA-1',
  ])
  for (const celula of celulas) expect(celula.classes()).not.toContain('sticky')
  expect(wrapper.get('thead').classes()).toContain('sticky')
})
it('mostra a condição adicional com rótulo curto e abre a descrição só da linha escolhida', async () => {
  const descricao =
    'Para cada vendedor do cargo 100 abrangido pela regra, acrescente um bônus fixo de R$ 350,00.'
  const comBonus = { ...linha, contribuicoes: { 'elem.1': 350, 'nucleo.taxas_por_cargo': 403.42 } }
  const wrapper = mount(RelatorioSimulacao, {
    attachTo: document.body,
    props: {
      aberto: true,
      carregando: false,
      erro: null,
      linhas: { '2025-08': { 'ALPHA-1': comBonus, 'BETA-2': comBonus } },
      regra: { nucleo: {}, especificacoes: [{ ref: 'elem.1', construto: 'generico', descricao }] },
    },
  })
  const [primeira, segunda] = wrapper.findAll('tbody tr')
  const botao = primeira!.get('button')
  const descricaoDa = (linhaDaTabela: typeof primeira) => {
    const controle = linhaDaTabela!.get('button').attributes('aria-controls')
    return linhaDaTabela!.get(`[id="${controle}"]`)
  }

  expect(primeira!.text()).toContain('Condição adicional · condição 1: R$ 350,00')
  expect(primeira!.text()).toContain('Taxas de comissão por cargo: R$ 403,42')
  expect(primeira!.findAll('button')).toHaveLength(1)
  expect(botao.text()).toBe('Ver descrição')
  expect(botao.attributes('aria-expanded')).toBe('false')
  expect(descricaoDa(primeira).isVisible()).toBe(false)

  await botao.trigger('click')

  expect(botao.text()).toBe('Ocultar descrição')
  expect(botao.attributes('aria-expanded')).toBe('true')
  expect(descricaoDa(primeira).isVisible()).toBe(true)
  expect(descricaoDa(primeira).text()).toBe(descricao)
  expect(segunda!.get('button').attributes('aria-expanded')).toBe('false')
  expect(descricaoDa(segunda).isVisible()).toBe(false)

  await botao.trigger('click')

  expect(descricaoDa(primeira).isVisible()).toBe(false)
  wrapper.unmount()
})
