import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RegraVersoes from './RegraVersoes.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'

describe('RegraVersoes', () => {
  it('mostra o reprodutor na entrada original por voz e pede o áudio dela', async () => {
    const wrapper = mount(RegraVersoes, { props: { registro: registroExemplo } })

    await wrapper.get('[data-reprodutor-audio] button').trigger('click')

    expect(wrapper.emitted('ouvir-audio')).toEqual([[registroExemplo.entradas[0]!.id]])
  })

  it.each(['formulario', 'texto'] as const)('não mostra reprodutor na entrada por %s', (tipo) => {
    const registro = structuredClone(registroExemplo)
    Object.assign(registro.entradas[0]!, { tipo, formato: undefined, conteudo: {} })

    const wrapper = mount(RegraVersoes, { props: { registro } })

    expect(wrapper.find('[data-reprodutor-audio]').exists()).toBe(false)
  })
})
