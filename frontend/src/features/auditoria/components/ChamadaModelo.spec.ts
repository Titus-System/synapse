import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChamadaModelo from './ChamadaModelo.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'

const chamada = registroExemplo.chamadas_modelo[2]!
afterEach(() => vi.unstubAllGlobals())

describe('ChamadaModelo', () => {
  it('vem recolhida e mostra etapa, modelo e tokens no resumo', () => {
    const wrapper = mount(ChamadaModelo, { props: { chamada } })
    expect(wrapper.get('details').attributes('open')).toBeUndefined()
    const resumo = wrapper.get('summary').text()
    expect(resumo).toContain('geracao_codigo')
    expect(resumo).toContain('gpt-4.1')
    expect(resumo).toContain('3120 tokens de entrada')
    expect(resumo).toContain('480 de saída')
  })

  it('não mostra zero quando o consumo de tokens não foi informado', () => {
    const semConsumo = structuredClone(chamada)
    delete semConsumo.resposta!.consumo_tokens
    const wrapper = mount(ChamadaModelo, { props: { chamada: semConsumo } })
    expect(wrapper.get('[data-tokens]').text()).toBe('Consumo não informado')
  })

  it('exibe prompt e resposta com marcação HTML como texto', () => {
    const perigosa = structuredClone(chamada)
    perigosa.prompt = '<script>alert(1)</script><b>x</b>'
    perigosa.resposta!.texto = '<img src=x onerror=alert(1)>'
    const wrapper = mount(ChamadaModelo, { props: { chamada: perigosa } })
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('b').exists()).toBe(false)
    expect(wrapper.text()).toContain('<script>alert(1)</script><b>x</b>')
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  })

  it('copia o prompt e a resposta inteiros', async () => {
    const escrever = vi.fn<(texto: string) => Promise<void>>().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText: escrever } })
    const wrapper = mount(ChamadaModelo, { props: { chamada } })
    const botoes = wrapper.findAll('button')
    await botoes[0]!.trigger('click')
    await botoes[1]!.trigger('click')
    expect(escrever).toHaveBeenNthCalledWith(1, chamada.prompt)
    expect(escrever).toHaveBeenNthCalledWith(2, chamada.resposta!.texto)
  })

  it('informa quando a resposta não foi registrada', () => {
    const semResposta = structuredClone(chamada)
    delete semResposta.resposta
    const wrapper = mount(ChamadaModelo, { props: { chamada: semResposta } })
    expect(wrapper.text()).toContain('Resposta não registrada')
    expect(wrapper.findAll('button')).toHaveLength(1)
    expect(wrapper.get('[data-tokens]').text()).toBe('Consumo não informado')
  })

  it('mantém a quebra de linha do texto copiado e exibido', () => {
    const wrapper = mount(ChamadaModelo, { props: { chamada } })
    expect(wrapper.findAll('pre')[1]!.text()).toContain('def aplicar_regra')
  })
})