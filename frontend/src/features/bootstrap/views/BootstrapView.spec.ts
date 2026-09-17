import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BootstrapView from './BootstrapView.vue'

describe('BootstrapView', () => {
  it('renderiza a entrada da aplicação', () => {
    const conteiner = mount(BootstrapView)

    expect(conteiner.get('h1').text()).toBe('Synapse')
    expect(conteiner.text()).toContain('Synapse A aplicação está funcionando.')
  })
})
