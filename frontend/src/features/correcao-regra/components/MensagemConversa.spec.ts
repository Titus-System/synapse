import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MensagemConversa from './MensagemConversa.vue'

describe('balões da conversa', () => {
  it.each([false, true])('distingue o autor e escapa conteúdo %s', (usuario) => {
    const wrapper = mount(MensagemConversa, {
      props: { usuario },
      slots: { default: '<p>&lt;script&gt;conteúdo&lt;/script&gt;</p>' },
    })
    expect(wrapper.find('script').exists()).toBe(false)
    expect(
      usuario
        ? wrapper.find('[aria-label="Você"]').exists()
        : wrapper.find('img[alt="Assistente"]').exists(),
    ).toBe(true)
  })
})
