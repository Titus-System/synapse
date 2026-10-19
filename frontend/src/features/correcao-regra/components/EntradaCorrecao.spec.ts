import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EntradaCorrecao from './EntradaCorrecao.vue'

describe('entrada da conversa', () => {
  it('mostra o limite e emite texto sem persistir o rascunho', async () => {
    const wrapper = mount(EntradaCorrecao, {
      props: { texto: '', habilitada: true, podeEnviar: false },
    })
    await wrapper.get('textarea').setValue('Minha correção')
    expect(wrapper.emitted('update:texto')).toEqual([['Minha correção']])
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ texto: 'Minha correção', podeEnviar: true })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('enviar')).toHaveLength(1)
    expect(wrapper.text()).toContain('4000 caracteres')
  })
  it('bloqueia a entrada durante a interpretação', () => {
    const wrapper = mount(EntradaCorrecao, {
      props: { texto: '', habilitada: false, podeEnviar: false },
    })
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })
})
