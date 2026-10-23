import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { RepresentacaoRegra, ResultadoLinhas } from '@/types/api'
import RelatorioSimulacaoPopup from './RelatorioSimulacaoPopup.vue'

const linha = (loja = '13', marca = '10', cargo = '100') => ({
  cod_loja: loja,
  cod_marca: marca,
  cod_cargo: cargo,
  comissao_baseline: 10,
  comissao_simulada: 10,
  diferenca: 0,
  contribuicoes: {},
})
const linhas: ResultadoLinhas = {
  '2025-08': { 'ALPHA-1': linha(), 'BETA-2': linha('58', '20', '150'), FORA: linha('3') },
  '2025-09': { 'ALPHA-1': linha('58'), 'GAMMA-3': linha() },
  '2025-10': { 'FORA-DA-VIGENCIA': linha() },
}
const regra: RepresentacaoRegra = {
  nucleo: {
    loja: ['13', '58'],
    marca: [],
    cargo: [],
    vigencia: { inicio: '2025-08', fim: '2025-09' },
  },
  especificacoes: [],
}
const montagens: ReturnType<typeof mount>[] = []
afterEach(() => {
  for (const wrapper of montagens.splice(0)) wrapper.unmount()
})
async function montar() {
  const wrapper = mount(RelatorioSimulacaoPopup, {
    attachTo: document.body,
    props: {
      aberto: false,
      carregando: false,
      erro: null,
      linhas,
      regra,
      decomposicao: {
        matricula: { 'ALPHA-1': 9876.54, 'BETA-2': 123.45 },
        loja_absoluto: { '13': 4567.89, '58': 5432.1, '99': 0 },
        competencia_absoluto: { '2025-08': 7890.12, '2025-09': 2109.87 },
      },
    },
  })
  montagens.push(wrapper)
  await wrapper.setProps({ aberto: true })
  await flushPromises()
  return wrapper
}
type Popup = Awaited<ReturnType<typeof montar>>
async function clicar(wrapper: Popup, texto: string) {
  await wrapper
    .findAll('button')
    .find((botao) => botao.text() === texto)!
    .trigger('click')
}
async function selecionar(wrapper: Popup, grupo: string, valores: string[]) {
  const campo = wrapper.findAll('fieldset').find((item) => item.get('legend').text() === grupo)!
  for (const codigo of valores) await campo.get(`input[value="${codigo}"]`).setValue(true)
}
it('abre nos filtros com nomes e opções restritas ao núcleo e vigência', async () => {
  const wrapper = await montar()
  expect(wrapper.get('dialog').attributes('open')).toBeDefined()
  expect(wrapper.find('table').exists()).toBe(false)
  const opcoes = wrapper
    .findAll('fieldset')
    .map((campo) => campo.findAll('input').map((input) => input.attributes('value')))
  expect(opcoes).toEqual([
    ['13', '58'],
    ['10', '20'],
    ['100', '150'],
    ['2025-08', '2025-09'],
  ])
  expect(wrapper.text()).toContain('PRETO')
  expect(wrapper.text()).toContain('GERENTE DE LOJA / GERENTE QUIOSQUE')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.findAll('tbody tr')).toHaveLength(4)
  expect(wrapper.get('tbody').text()).not.toContain('FORA')
})
it('combina OR em cada dimensão e AND entre dimensões, sem remover delta zero', async () => {
  const wrapper = await montar()
  await selecionar(wrapper, 'Lojas', ['13', '58'])
  await selecionar(wrapper, 'Marcas', ['10'])
  await selecionar(wrapper, 'Cargos', ['100'])
  await selecionar(wrapper, 'Competências', ['2025-08', '2025-09'])
  await wrapper.get('input[type="search"]').setValue('lPhA')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  expect(wrapper.get('tbody').text()).not.toContain('BETA')
  expect(wrapper.get('tbody').text()).toContain('R$ 0,00')
})
it('limpa os refinamentos sem ampliar o escopo e preserva os valores aplicados na reabertura', async () => {
  const wrapper = await montar()
  await selecionar(wrapper, 'Lojas', ['58'])
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  await wrapper.setProps({ aberto: false })
  await wrapper.setProps({ aberto: true })
  await flushPromises()
  expect(wrapper.get('input[value="58"]').element).toHaveProperty('checked', true)
  await clicar(wrapper, 'Limpar filtros')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.findAll('tbody tr')).toHaveLength(4)
  expect(wrapper.get('tbody').text()).not.toContain('FORA')
})
it('mostra totais independentes da API depois da tabela, inclusive num cruzamento vazio', async () => {
  const wrapper = await montar()
  await selecionar(wrapper, 'Lojas', ['13', '58'])
  await selecionar(wrapper, 'Marcas', ['20'])
  await selecionar(wrapper, 'Cargos', ['100'])
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.text()).toContain('Nenhum registro encontrado')
  const totais = wrapper.get('[aria-label="Totais da simulação"]')
  expect(totais.text()).toContain('R$ 4.567,89')
  expect(totais.text()).toContain('R$ 5.432,10')
  expect(totais.text()).toContain('R$ 9.876,54')
  expect(totais.text()).not.toContain('R$ 0,00')
  await clicar(wrapper, 'Alterar filtros')
  await clicar(wrapper, 'Limpar filtros')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.html().indexOf('<table')).toBeLessThan(
    wrapper.html().indexOf('Totais da Simulação'),
  )
})
it('pagina e volta à primeira página ao aplicar outro filtro', async () => {
  const wrapper = await montar()
  await wrapper.setProps({
    linhas: {
      '2025-08': Object.fromEntries(Array.from({ length: 90 }, (_, i) => [`COL-${i}`, linha()])),
    },
  })
  await clicar(wrapper, 'Aplicar filtros')
  await wrapper.get('[aria-label="Páginas do relatório"]').findAll('button')[1]!.trigger('click')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 2')
  await clicar(wrapper, 'Alterar filtros')
  await wrapper.get('input[type="search"]').setValue('COL')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.get('[role="status"]').text()).toContain('Página 1')
  expect(wrapper.findAll('tbody tr')).toHaveLength(25)
})
it('distingue escopo histórico ausente de declaração universal e usa competências descontínuas do job', async () => {
  const wrapper = await montar()
  await wrapper.setProps({
    regra: { nucleo: { marca: [] }, especificacoes: [] },
    competenciasDoJob: ['2025-08', '2025-10'],
  })
  expect(wrapper.text()).toContain('não registrou todas as dimensões')
  expect(wrapper.findAll('fieldset')[3]!.text()).not.toContain('09/2025')
  await clicar(wrapper, 'Aplicar filtros')
  expect(wrapper.get('tbody').text()).toContain('FORA')
  expect(wrapper.get('tbody').text()).not.toContain('GAMMA')
})
it('distingue carregamento, falha com retry e ausência de detalhamento', async () => {
  const wrapper = await montar()
  await wrapper.setProps({ carregando: true })
  expect(wrapper.get('[role="status"]').text()).toContain('Carregando')
  await wrapper.setProps({ carregando: false, erro: 'Falha segura' })
  expect(wrapper.get('[role="alert"]').text()).toContain('Falha segura')
  await clicar(wrapper, 'Tentar novamente')
  expect(wrapper.emitted('tentarNovamente')).toHaveLength(1)
  await wrapper.setProps({ erro: null, linhas: undefined })
  expect(wrapper.text()).toContain('O detalhamento não está disponível')
})
it('fecha pelo controle e Escape e devolve o foco ao acionador', async () => {
  const wrapper = await montar()
  expect(document.activeElement).toBe(
    wrapper.findAll('button').find((botao) => botao.text() === 'Fechar relatório')!.element,
  )
  await clicar(wrapper, 'Fechar relatório')
  expect(wrapper.emitted('alternar')).toHaveLength(1)
  await wrapper.setProps({ aberto: false })
  await flushPromises()
  expect(document.activeElement).toBe(
    wrapper.findAll('button').find((botao) => botao.text() === 'Abrir relatório')!.element,
  )
  await wrapper.setProps({ aberto: true })
  await flushPromises()
  await wrapper.get('dialog').trigger('cancel')
  expect(wrapper.emitted('alternar')).toHaveLength(2)
})

it('mantém o ciclo de Tab e Shift+Tab entre os controles visíveis do diálogo', async () => {
  const wrapper = await montar()
  const retangulos = vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(() =>
    Object.assign([new DOMRect(0, 0, 10, 10)], {
      item: (indice: number) => (indice === 0 ? new DOMRect(0, 0, 10, 10) : null),
    }),
  )
  try {
    const fechar = wrapper.findAll('button').find((botao) => botao.text() === 'Fechar relatório')!
    const limpar = wrapper.findAll('button').find((botao) => botao.text() === 'Limpar filtros')!
    const botaoFechar = fechar.element as HTMLButtonElement
    botaoFechar.focus()
    await fechar.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(limpar.element)
    await limpar.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(fechar.element)
  } finally {
    retangulos.mockRestore()
  }
})
it('mostra a condição adicional recolhida na tabela do popup', async () => {
  const descricao = 'Bônus fixo de R$ 350,00 para vendas iguais ou superiores a R$ 40.000,00.'
  const wrapper = await montar()
  await wrapper.setProps({
    linhas: { '2025-08': { 'ALPHA-1': { ...linha(), contribuicoes: { 'elem.1': 350 } } } },
    regra: { ...regra, especificacoes: [{ ref: 'elem.1', construto: 'generico', descricao }] },
  })
  await clicar(wrapper, 'Aplicar filtros')
  const botao = wrapper.get('tbody button')
  const texto = () => wrapper.get(`[id="${botao.attributes('aria-controls')}"]`)

  expect(wrapper.get('tbody').text()).toContain('Condição adicional · condição 1: R$ 350,00')
  expect(botao.attributes('aria-expanded')).toBe('false')
  expect(texto().isVisible()).toBe(false)

  await botao.trigger('click')

  expect(texto().isVisible()).toBe(true)
  expect(texto().text()).toBe(descricao)
})
