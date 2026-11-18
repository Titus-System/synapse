import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ConversaPython from './ConversaPython.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'

describe('ConversaPython', () => {
  it('mostra a conversa e o código lado a lado, com a mesma altura', () => {
    const wrapper = mount(ConversaPython, { props: { registro: registroExemplo } })
    const colunas = wrapper.get('[data-conversa-python]').element.children
    expect(colunas).toHaveLength(2)
    for (const coluna of Array.from(colunas)) {
      expect(coluna.className).toContain('xl:h-full')
      expect(coluna.className).toContain('h-[70vh]')
    }
    expect(wrapper.find('[aria-label="Conversa registrada"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Código gerado"]').exists()).toBe(true)
  })

  it('dá rolagem própria à conversa e ao código', () => {
    const wrapper = mount(ConversaPython, { props: { registro: registroExemplo } })
    expect(wrapper.get('ol').classes()).toContain('overflow-y-auto')
    expect(wrapper.get('[aria-label="Fonte do código"]').classes()).toContain('overflow-auto')
  })
})