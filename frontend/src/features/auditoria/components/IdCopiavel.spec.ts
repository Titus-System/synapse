import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import IdCopiavel from './IdCopiavel.vue'

const id = '0bbc1cae-da75-5fe0-ab91-52240a99454c'
afterEach(() => vi.unstubAllGlobals())

describe('IdCopiavel', () => {
  it('mostra o id curto e guarda o completo no title', () => {
    const wrapper = mount(IdCopiavel, { props: { id } })
    expect(wrapper.text()).toContain('0bbc1cae…')
    expect(wrapper.text()).not.toContain(id)
    expect(wrapper.get('[title]').attributes('title')).toBe(id)
  })

  it('mantém o id que já é curto', () => {
    expect(mount(IdCopiavel, { props: { id: 'sim-1' } }).text()).toContain('sim-1')
  })

  it('copia o id completo', async () => {
    const escrever = vi.fn<(t: string) => Promise<void>>().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText: escrever } })
    const wrapper = mount(IdCopiavel, { props: { id } })
    await wrapper.get('button').trigger('click')
    expect(escrever).toHaveBeenCalledWith(id)
    expect(wrapper.text()).toContain('Copiado')
  })

  it('avisa quando a cópia falha', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn<(t: string) => Promise<void>>().mockRejectedValue(new Error('x')) },
    })
    const wrapper = mount(IdCopiavel, { props: { id } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível copiar')
  })
    it('no modo só botão não mostra o id, nem o curto', () => {
    const wrapper = mount(IdCopiavel, { props: { id, somenteBotao: true } })
    expect(wrapper.text()).not.toContain('0bbc1cae')
    expect(wrapper.get('button').attributes('title')).toBe(id)
  })

  it('no modo só botão copia o id completo', async () => {
    const escrever = vi.fn<(t: string) => Promise<void>>().mockResolvedValue()
    vi.stubGlobal('navigator', { clipboard: { writeText: escrever } })
    const wrapper = mount(IdCopiavel, { props: { id, somenteBotao: true } })
    await wrapper.get('button').trigger('click')
    expect(escrever).toHaveBeenCalledWith(id)
  })
})