import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CodigoAuditoria from './CodigoAuditoria.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'
import { useConversaAuditoria } from '../composables/useConversaAuditoria'

function montar(registro = registroExemplo) {
  const { codigos } = useConversaAuditoria(registro)
  return mount(CodigoAuditoria, { props: { codigos: codigos.value } })
}
afterEach(() => vi.unstubAllGlobals())

describe('CodigoAuditoria', () => {
  it('numera as linhas sem criar uma linha fantasma depois do \\n final', () => {
    const wrapper = montar()
    const fonte = registroExemplo.codigos[0]!.fonte
    expect(wrapper.findAll('[data-linha]')).toHaveLength(fonte.split('\n').length - 1)
  })

  it('identifica o código, a versão e o escopo da regra', () => {
    const texto = montar().text()
    expect(texto).toContain('Código 1')
    expect(montar().get('dd[title]').attributes('title')).toBe(registroExemplo.codigos[0]!.id)
    expect(texto).toContain('v2')
    expect(montar().get('[data-escopo]').text()).toBe('13 / 10, 20 / 100, 300')
  })

  it('só mostra o seletor quando há mais de um código', async () => {
    expect(montar().find('select').exists()).toBe(false)
    const registro = structuredClone(registroExemplo)
    registro.codigos.push({ ...registro.codigos[0]!, id: 'outro-codigo-123', fonte: 'x = 1\n' })
    const wrapper = montar(registro)
    expect(wrapper.find('select').exists()).toBe(true)
    expect(wrapper.get('select').text()).toContain('Código 2')
    await wrapper.get('select').setValue(1)
    expect(wrapper.get('dd[title]').attributes('title')).toBe('outro-codigo-123')
  })

  it('copia a fonte inteira', async () => {
    const escrever = vi.fn<(texto: string) => Promise<void>>().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText: escrever } })
    const wrapper = montar()
    const botao = wrapper.findAll('button').find((b) => b.text() === 'Copiar código')!
    await botao.trigger('click')
    expect(escrever).toHaveBeenCalledWith(registroExemplo.codigos[0]!.fonte)
    expect(wrapper.text()).toContain('Código copiado')
  })

  it('copia o id completo do código', async () => {
    const escrever = vi.fn<(texto: string) => Promise<void>>().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText: escrever } })
    const wrapper = montar()
    await wrapper.findAll('button').find((b) => b.text() === 'Copiar id')!.trigger('click')
    expect(escrever).toHaveBeenCalledWith(registroExemplo.codigos[0]!.id)
  })

  it('avisa quando a cópia falha', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn<(t: string) => Promise<void>>().mockRejectedValue(new Error('x')) },
    })
    const wrapper = montar()
    const botao = wrapper.findAll('button').find((b) => b.text() === 'Copiar código')!
    await botao.trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível copiar')
  })

  it('exibe marcação HTML como texto', () => {
    const registro = structuredClone(registroExemplo)
    registro.codigos[0]!.fonte = '<script>alert(1)</script>\n<b>negrito</b>\n'
    const wrapper = montar(registro)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('b').exists()).toBe(false)
    expect(wrapper.text()).toContain('<script>alert(1)</script>')
  })

  it('informa quando não há código', () => {
    const registro = structuredClone(registroExemplo)
    registro.codigos = []
    expect(montar(registro).text()).toContain('Nenhum código registrado')
  })
})